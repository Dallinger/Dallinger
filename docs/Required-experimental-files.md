Wallace is flexible with regards to the form the front end takes. However, there are a number of required or forbidden files. You can verify that a directory is compatible by running [`wallace verify`](https://github.com/berkeley-cocosci/Wallace/wiki/Command-line-utility#verify) from a terminal within the directory. Though just because these checks pass doesn't mean the experiment will run! The minimal required structure is as follows:

![](https://github.com/berkeley-cocosci/Wallace/blob/master/wiki/images/directories.jpg)

Blue items are (optional) directories (note that the experiment directory can have any name), green items are required files (the README file can be either a txt file or a md file), and red items are forbidden files that will cause a conflict at run time. 

#### Required files

+ config.txt - The config file contains a variety of parameters that affect how Wallace runs. For more info see...

+ experiment.py - This is a python file containing the custom experiment code.

+ README.txt/md - This (hopefully) contains a helpful description of the experiment.

#### Forbidden files

A number of files cannot be included in the experiment directory. This is because, when Wallace runs, it inserts a number of required files into the experiment directory and will overwrite any files with the same name. The files are as follows:

+ complete.html - this html page shows when wallace is run in debug mode and the experiment is complete.
+ error_wallace.html - this is a flexible error page that shows when something goes wrong.
+ launch.html - this page is shown when the /launch route is pinged and the experiment starts successfully.
+ robots.txt - this file is returned to bots (e.g. from google) that bump into the experiment when crawling the internet.
+ wallace.js - this is a javascript library with a number of helpful functions.
+ [reqwest.min.js](https://github.com/ded/reqwest) - this is required for wallace.js to work.
+ wallace.css - this contains several css classes that are used in the examples.
