	// Utilities for running psychology experiments.
	// Particulary useful for pre/post experiment
	// questionaires
	var tu = {};
	
	// array of image DOM elements. This 
	// disables some simple attributes
	tu.protectImages = function (list_img_DOM) {
		$(list_img_DOM).attr('ondrag',"return false")
					   .attr('ondragstart',"return false")
					   .attr('oncontextmenu',"return false")
					   .attr('galleryimg',"no")
					   .attr('onmousedown',"return false");
		return list_img_DOM;			   
	};
	
	// randomize the order of elements in an array
    tu.shuffle = function ( myArray ) {
        var i = myArray.length;
        if ( i == 0 ) return false;
        while ( --i ) {
         var j = Math.floor( Math.random() * ( i + 1 ) );
         var tempi = myArray[i];
         var tempj = myArray[j];
         myArray[i] = tempj;
         myArray[j] = tempi;
        }
        return myArray;
    };
    
    // get a random integer between lb and ub, inclusive
    tu.randint = function (lb,ub) {
    	if (ub < lb) {
    		throw new Error('invalid call of randint');
    	}   	
    	var range = ub-lb+1;
    	var out = Math.floor( Math.random()*range) + lb;
    	return out;
    }
    
    // generate a random permutation of a vector
    // starting at first_elem:last_elem
    tu.randperm = function (first_elem,last_elem) {
    	var perm = new Array();
    	for (var i=first_elem; i<=last_elem; i++) {
    		var j=i-first_elem;
    		perm[j] = i;
    	}    	
    	perm = tu.shuffle(perm);
    	return perm;
    };
    
    // apply permutation
    tu.apply_perm = function (myArray,perm) {
    	if (myArray.length !== perm.length) {
    		throw new Error('permutation is the wrong length');
    	}
    	var n = myArray.length;
    	var newArray = new Array();
    	for (var i=0; i<n; i++) {
    		newArray[i] = myArray[perm[i]];
    	}
    	return newArray;
    };

	// get value of checked radio button
	tu.getRadioCheckedValue = function (radio_name) {
	    var oRadio = document.getElementsByName(radio_name);
	    for (var i = 0; i < oRadio.length; i++) {
	          if (oRadio[i].checked) {
	             return oRadio[i].value;
	          }
	     }
	     return '';
    };
    
    //
    // Get all of the radio buttons with a particular class.
    // Return a list of objects with name/value pairs
    //
    // Input: radio_class is a string identifying the class of radio buttons
    tu.getSurveyRadios = function (radio_class) {
    	var rnames = $('.'+radio_class).get_attr('name');
    	rnames = rnames.unique();
    	var n = rnames.length;
    	// if (n===0) {throw new Error('jQuery did not find any survey radio buttons.'); }
    	var list = [];
    	for (var i=0; i<n; i++) {
    		var val = tu.getRadioCheckedValue(rnames[i]);
    		list[i] = {name : rnames[i], value : val};
    	}
    	return list;    	
    };
    
    //
    // Get all of the text areas with a particular class.
    // Return a list of objects with name/value pairs
    //
    // Input: text_class is a string identifying the class of text areas
    tu.getSurveyText = function (text_class) {
    	var tnames = $('.'+text_class).get_attr('id');
    	var n = tnames.length;
    	// if (n===0) {throw new Error('jQuery did not find any survey text.'); }
    	var list = [];
    	for (var i=0; i<n; i++) {
    		var val = $('#'+tnames[i]).val();
    		list[i] = {name : tnames[i], value : val};
    	}
    	return list;
    };
    
    // Get value of a name/value pair from the survey
    tu.getValue = function (str,list_objs) {
    	var n = list_objs.length;
    	for (var i=0; i<n; i++) {
    		if (str === list_objs[i].name) {
    			return list_objs[i].value;
    		}
    	}
    	return undefined;
    };
    
    // Does the name in the name/value pair have an empty value?
    tu.emptyField = function (str,list_objs) {
    	var value = tu.getValue(str,list_objs);
    	if (value === '') {
    		return true;
    	}
    	else if (value === undefined) {
    		throw new Error('This field is not defined.');
    	}
    	return false;
    };
    
    // create lines of matlab to display
    // all the url parameters
    tu.printUrlParams = function () {
    	var list_p = $.url().param();    	
    	var keys = Object.keys(list_p);
    	var n = keys.length;
    	var out = '';
    	for (var i=0; i<n; i++) {
    		out = out + "s." + keys[i] + "='" + list_p[keys[i]] + "'; ";
    	}
		return out;    		
    };
    
    // create a line of matlab to save a field
    // from the survey
    tu.printFields = function (list_objs) {
    	var n = list_objs.length;
    	var out = "";
    	for (var i=0; i<n; i++) {
    		var name = list_objs[i].name;
    		var value = list_objs[i].value;    		
			value = value.replace(/(\r\n|\n|\r)/gm," ");
			value = value.replace(/["']/g, "");    	
	    	out = out + "s." + name + "='" + value + "'; ";
    	}
    	return out;
    };
    
    // print the drawing associated with each canvas
    // to lines of matlab code
    tu.printListCanvas = function (list_canvas) {
    	var n = list_canvas.length;
    	var out = "";
    	for (var i=0; i<n; i++) {
    		var stk = list_canvas[i].getDrawing();
    		var img = list_canvas[i].getImage();
    		var img_name = list_canvas[i].imageName();
    		stk = stk.replace(/'/g,"''");
    		var indx = i+1;
    		out = out + "s.strokes{" + (i+1) + "}=";
    		out = out +  "'" + stk +  "'; ";
    		out = out + "s.image{" + (i+1) + "}=";
    		out = out +  "'" + img +  "'; ";
    		out = out + "s.input_image{" + (i+1) + "}=";
    		out = out +  "'" + img_name + "'; ";
    	}
    	return out;	    	
    };
    
    // clear the "checked" feature on all radio buttons
	tu.clearRadio = function (radio_name) {
	    var oRadio = document.getElementsByName(radio_name);
	    for (var i = 0; i < oRadio.length; i++) {
	          oRadio[i].checked = false;
	    }
    };
    
    // see if all of the quiz answers are correct.
    // Quiz must be all radio buttons, with a value="1"
    // for correct answers
    //
    // Input: list_qs is an array of question names
    // Output: number of missed questions
    tu.checkQuiz = function (list_qs) {
    	var n = list_qs.length;
    	var list_ans = [];
    	for (var i=0; i<n; i++) { // get all answers
    		list_ans[i] = tu.getRadioCheckedValue(list_qs[i]);
    		tu.clearRadio(list_qs[i]);
    	}
		    	
        var corr = 0;
        for (var i=0; i<n; i++) { // record if they are correct
        	if (list_ans[i] !== '' && parseInt(list_ans[i]) === 1) {
        		corr += 1;
        	}
        }
    	
    	// return number of misses
    	var nmiss = n - corr;
    	return nmiss;
    };
    
    // change the HTML display to a different section.
    //
    // sections must be DIVs marked with class=.task_selection
    tu.changeDisplay = function (display,myclass) {
        $('.'+myclass).attr('style','display:none;');
        var str_sel = '#'+display;
        if ($(str_sel).exists()) {
        	$(str_sel).attr('style','');
        }
        else if (display === '')
        {
        }
        else {
        	throw new Error("invalid display option");
        } 
    };
    
    // check workerId against list of workers
    tu.flagWhiteList = function () {
        var url = $.url();
        var wID = url.param('workerId');        
        var listID  = url.param('access');
        if (wID == null || listID == null) {
            return false;
        }
        var arrayExclude = listID.split(",");
        var n = arrayExclude.length;
        for (var i=0; i < n; i++) {
            str = arrayExclude[i];
            if (str === wID) {
                return true
            }
        }
        return false;
    };
    
    // check workerId against list of workers
    tu.flagRepeatWorker = function () {
        var url = $.url();
        var wID = url.param('workerId');        
        var excludeID  = url.param('exclude');
        if (wID === null) {
            return false;
        }
        if (excludeID !== undefined && excludeID !== null) {
        	throw new Error('taskutil: The exclude parameter is no longer allowed');
           	return true;	
        }        
        if (exclude === undefined) {
        	throw new Error('taskutil: The exclude variable should not be undefined');
        	return true;	
        }
        var listID = exclude;
        var arrayExclude = listID.split(",");
        var n = arrayExclude.length;
        for (var i=0; i < n; i++) {
            str = arrayExclude[i];
            if (str === wID) {
                return true
            }
        }
        return false;
    };
    
    // return true if they are using the Chrome browser
    tu.flagChrome = function () {
    	return (/chrom(e|ium)/.test(navigator.userAgent.toLowerCase())); 		
    };
    
    // return true if they are using Internet Explorer
    tu.flagIE = function () {
        var ua = window.navigator.userAgent;
        var msie = ua.indexOf("MSIE ");
        if (msie > 0 || !!navigator.userAgent.match(/Trident.*rv\:11\./)) {
            return true;
        }
        else {
            return false;
        }       
    };

    // return true if this page is being viewed from preview mode
	tu.inPreviewMode = function () {
		var url = $.url();
		var aID = url.param('assignmentId');
		if (aID === 'ASSIGNMENT_ID_NOT_AVAILABLE') {
			return true;	
		}
		return false;
	};
	
	// Set the form POST action to be correct, if we are using the sandbox
	tu.setPostURL = function () {
		var sandbox = document.referrer && ( document.referrer.indexOf('workersandbox') != -1)
		if (sandbox) {
			$('#myform').attr('action','https://workersandbox.mturk.com/mturk/externalSubmit');
		}
		else {
			$('#myform').attr('action','https://www.mturk.com/mturk/externalSubmit');
		}
	};
	
	// get time in milliseconds since mindnight, 1 Jan 1970
   tu.getTimeMilli = function () {
   		var ms = new Date().getTime();
   		return ms;
   };
	
	// get time in seconds since mindnight, 1 Jan 1970
   tu.getTime = function () {
   		var ms = tu.getTimeMilli();
   		return ms / 1000;
   };