"""
   DecMeg2014 2nd place submission code. 

   Heikki.Huttunen@tut.fi, Jul 29th, 2014

   The model is a hierarchical combination of logistic regression and 
   random forest. The first layer consists of a collection of 337 logistic 
   regression classifiers, each using data either from a single sensor 
   (31 features) or data from a single time point (306 features). The 
   resulting probability estimates are fed to a 1000-tree random forest, 
   which makes the final decision. 
   
   The model is wrapped into the LrCollection class.
   The prediction is boosted in a semisupervised manner by
   iterated training with the test samples and their predicted classes
   only. This iteration is wrapped in the class IterativeTrainer.
   
   Requires sklearn, scipy and numpy packages.
   
===
Copyright (c) 2014, Heikki Huttunen 
Department of Signal Processing
Tampere University of Technology
Heikki.Huttunen@tut.fi

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the Tampere University of Technology nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

# Generic imports 

import numpy as np
from scipy.io import loadmat
from scipy.signal import lfilter, decimate
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier

import time
import sys
import copy 
import datetime
import os.path
import json
import cPickle as pickle

from LrCollection import LrCollection
from IterativeTrainer import IterativeTrainer

def loadData(filename,
             downsample = 8, 
             start = 130, 
             stop = 375):
    """
    Load, downsample and normalize the data from one test subject.
    
    Args:

        filename:   input mat file name
        downsample: downsampling factor
        start:      first time index in the result array (in samples)
        stop:       last time index in the result array (in samples)
    
    Returns: 
        
        X:          the 3-dimensional input data array
        y:          class labels (None if not available)
        ids:        the sample Id's of the samples, e.g., 17000, 17001, ...
                    (None if not available)
        
    """
    
    print "Loading " + filename + "..."
    data = loadmat(filename, squeeze_me=True)
    X = data['X']
   
    # Class labels available only for training data.
   
    try:
        y = data['y']
    except:
        y = None

    # Ids available only for test data

    try:
        ids = data['Id']
    except:
        ids = None

    # Decimate the time dimension (lowpass filtering + resampling)

    X = decimate(X, downsample)
    
    # Extract only the requested time span
    
    startIdx = int(start / float(downsample) + 0.5)
    stopIdx  = int(stop / float(downsample) + 0.5)
    X = X[..., startIdx:stopIdx]

    # Normalize each measurement

    X = X - np.mean(X, axis = 0)
    X = X / np.std(X, axis = 0)
    
    return X, y, ids
    
def run(modelpath = "models",
        testdatapath = "data",
        submissionpath = "submissions",
        C = 0.1, 
        numTrees = 1000,
        downsample = 8, 
        start = 130, 
        stop = 375, 
        relabelThr = 1.0, 
        relabelWeight = 1,
        iterations = 1,
        substitute = True):
    """
    Run training and prepare a submission file.
    
    Args:
    
        datapath:        Directory where the training .mat files are located.  
        C:               Regularization parameter for logistic regression
        numTrees:        Number of trees in random forest
        downsample:      Downsampling factor in preprocessing
        start:           First time index in the result array (in samples)
        stop:            Last time index in the result array (in samples)
        relabelThr:      Threshold for accepting predicted test samples in 
                         second iteration (only used if substitute = False)
        relabelWeight:   Duplication factor of included test samples 
                         (only used if substitute = False)
        substitute:      If True, original training samples are discarded
                         on second training iteration. Otherwise test
                         samples are appended to training data.    
        estimateCvScore: If True, we do a full 16-fold CV for each training 
                         subject. Otherwise only final submission is created.
     
    Returns:
    
        Nothing.
        
    """

    print "DecMeg2014: https://www.kaggle.com/c/decoding-the-human-brain"
    print "[2nd place submission. Heikki.Huttunen@tut.fi]"

    X_test = []         # Test data
    ids_test = []       # Test ids
    labels_test = []    # Subject number for each trial in test data

    subjects_test = range(17,24)
    
    print "Loading %d test subjects." % (len(subjects_test))
        
    for subject in subjects_test:

        filename = os.path.join(testdatapath, 'test_subject%02d.mat' % subject)

        XX, yy, ids = loadData(filename = filename, 
                               downsample = downsample,
                               start = start, 
                               stop = stop)

        X_test.append(XX)
        labels_test = labels_test + ([subject] * XX.shape[0])
        ids_test.append(ids)

    X_test = np.vstack(X_test)
    ids_test = np.concatenate(ids_test)
    print "Testset:", X_test.shape
    
    filename_submission = os.path.join(submissionpath, "submission.csv")
    print "Submission file: ", filename_submission
    
    # Write header for the csv file
    
    with open(filename_submission, "w") as f:
        f.write("Id,Prediction\n")
        
    # Train a subjective model for each test subject.
        
    for subject in subjects_test:

        filename = "model%d.pkl" % subject
        pkl_file = open(os.path.join(modelpath, filename), "rb")
        clf = pickle.load(pkl_file)
        pkl_file.close()
        
        # Find trials for this test subject:
        
        idx = [i for i in range(len(ids_test)) if ids_test[i] / 1000 == subject]
        
        X_subj = X_test[idx,...]
        id_subj = ids_test[idx]
        
        print "Predicting."
        y_subj = clf.predict(X_subj)

        # Append predicted labels to file.

        with open(filename_submission, "a") as f:
            for i in range(y_subj.shape[0]):
                f.write("%d,%d\n" % (id_subj[i], y_subj[i]))

    print "Done."

if __name__ == "__main__":
    """
    Set training parameters and call main function.
    """

    f = open("SETTINGS.json", "r")
    settings = json.load(f)
    modelpath = settings["MODEL_PATH"]
    testdatapath = settings["TEST_DATA_PATH"]
    submissionpath = settings["SUBMISSION_PATH"]
    f.close()
    datapath = "data"
    C = 10. ** -2.25
    numTrees = 100
    relabelWeight = 1
    relabelThr = 0.1
    downsample = 8
    start = 130
    stop = 375
    substitute = True
    iterations = 2
        
    run(modelpath = modelpath,
        testdatapath = testdatapath,
        submissionpath = submissionpath,
        C = C, 
        numTrees = numTrees,
        relabelThr = relabelThr, 
        relabelWeight = relabelWeight, 
        iterations = iterations,
        downsample = downsample, 
        start = start, 
        stop = stop, 
        substitute = substitute)
