//
// Interface to Jason's canvas objects.
//
// Input
//  name: name given to canvas elements
//  imageobj: DOM image object associated with the model
//  imageback: (optional) DOM image object we want to draw over
//  showImageHalf: (optional) either "top","bottom","left","right"
//
var canvasobj = function (name,imageobj,imageback,showImageHalf) {

	var width = imageobj.width; //105;
	var height = imageobj.height; //105;
	var lineWidth = 1; // Jason used 5
	var canvas; // canvas object
	var tableDom; // dom object

	// make cell that stores image
	var makeImgCell = function () {
		return $('<tr/>').append(
				 $('<td/>').attr('valign','middle')
				 		   .attr('align','center')
				 		   .append(imageobj));
	};

	// make cell that stores canvas
	var makeCanvasCell = function () {
		if (imageback === undefined) {
			canvas = new DrawingCanvas(name+'_canvas',width,height,lineWidth);
			return $('<tr/>').append(
				 $('<td/>').attr('valign','middle')
				 		   .attr('align','center')
				 		   .append(canvas.DOMElement));
		}
		else {
			canvas = new CompletionCanvas(name+'_canvas',width,height,imageback,showImageHalf,lineWidth);
			return $('<tr/>').append(
				 $('<td/>').attr('valign','middle')
				 		   .attr('align','center')
				 		   .append(canvas.DOMElement));
		}
	};

	// make a table that image/canvas pair
	(function () {
		if (imageback !== undefined) {
			if (showImageHalf === "left" || showImageHalf === "right" || showImageHalf === "bottom" || showImageHalf === "top")
			{ }
			else {
				throw new Error('invalid background image display parameter');
			}
		}
		tableDom = $('<div/>').attr('class','table');
		tableDom = tableDom.append(  $('<table/>').append(makeImgCell())
		   					  					  .append(makeCanvasCell()) );
	})();

    // public methods
    return {

    	// return string with the drawing trace
    	getDrawing : function () {
    		return canvas.strokesToString();
    	},

    	// return string with image in data:url format
    	getImage : function () {
    		return canvas.getImage();
    	},

    	// return the name of the input image
    	imageName : function () {
    		return $(imageobj).attr('src');
    	},

    	// return the DOM object associated with the canvas/image pair
    	getDOMelem : function () {
    		return tableDom;
    	},

    	// is the canvas empty?
    	isEmpty : function () {
    		var str_out = canvas.strokesToString();
    		if (str_out === '[]') {
    			return true;
    		}
    		return false;
    	},
    }
};
