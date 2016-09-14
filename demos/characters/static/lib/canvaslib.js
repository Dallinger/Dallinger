//
// Jason Gross's code for a canvas drawing object
//
// Inputs
//   onRedraw: a function to perform when the canvas is cleared
//
var JQuery = $;
var DrawingCanvas; // variable to store function handle, so we can construct the object

// anonymous function, called with arguments (5, 'butt', jQuery, jQuery)
(function (defaultLineWidth, defaultLineCap, $, jQuery, undefined) {

  // set variable to be function handle
  DrawingCanvas = function DrawingCanvas(name, width, height, canvasLineWidth, canvasLineCap, canvas, onRedraw, drawAtPoint, interpolate) {

    if (canvasLineWidth === undefined) canvasLineWidth = defaultLineWidth; // set as 5
    if (canvasLineCap === undefined) canvasLineCap = defaultLineCap; // set as 'butt'

    var self = this; // save copy of function before doing anything
    this.name = name; // should be the canvas id field

    width = parseInt(width); height = parseInt(height);
    if (canvas === undefined)
      canvas = "<canvas>Your browser must support the &lt;canvas&gt; element in order to use this site.</canvas>";

    // sets canvas size
    this.canvas = canvas = $(canvas)
      .attr('id', name)
      .attr('width', width)
      .attr('height', height);

    // Assign functionality to buttons.
    // This use of query creates <a></a> tags, but doesn't attach them to the DOM yet
    var clearLink = $('<a/>')
      .attr('id', 'clear')
      .attr('href', '#')
      .append('clear')
      .click(function () { self.clear(); return false; });
    var undoLink = $('<a/>')
      .attr('id', 'undo')
      .attr('href', '#')
      //.append(' ') //.append('undo') // commented out by Jason
      .click(function () { self.undo(); return false; });
    var redoLink = $('<a/>')
      .attr('id', 'redo')
      .attr('href', '#')
      //.append('redo') // commented out by Jason
      .click(function () { self.redo(); return false; });

    // This is the entire DOM element for the canvas (the canvas plus the buttons)
    this.DOMElement = $('<div/>')
      .append($('<div/>')
                .attr('id', name + '_div')
                .append(this.canvas))
      .append($('<div/>')
                .attr('id', 'canvascontrols')
                .append(clearLink)
                .append(undoLink)
                .append(redoLink));

    // handler for 'dirty' and 'dirtyImage' events
    // Note: do I need this?
    (function events() {
      var events = {'dirty':[], 'dirtyImage':[]};
      jQuery.each(events, function (key) {
          self[key] = function (handler) {
            if (handler === undefined) {
              var len = events[key].length;
              for (var i = 0; i < len; i++) {
                events[key][i]();
              }
            } else {
              events[key].push(handler);
            }
          };
          self[key].name = key;
        });
    })();
    self.dirtyImage(self.dirty);

    // get the canvas element on the page
    var ctx = canvas[0].getContext('2d');

    var drawStroke, drawEnd, clearDrawing;
    (function drawing(ctx) {
      var isDrawing = false;
      var lastPt = undefined;

      // place ink on the screen, depending on whether or not we are in bounds
      drawStroke = function drawStroke(x, y, force) {

        if (drawAtPoint === undefined || drawAtPoint(x, y) || force) { // if we are in the bounded box of the canvs
          if (isDrawing) { // continue a stroke
            ctx.lineTo(x, y);
            ctx.stroke();
            // start a new stroke
          } else {
            ctx.fillRect(x-ctx.lineWidth/2, y-ctx.lineWidth/2, ctx.lineWidth, ctx.lineWidth);
            ctx.beginPath();
            ctx.moveTo(x, y);
            isDrawing = true;
          }
          lastPt = {'x':x, 'y':y};

        } else if (isDrawing) { // if we were drawing, turn off drawing. We are out of bounds!
          isDrawing = false;
          if (lastPt !== undefined && interpolate) {
            var pt = interpolate(lastPt.x, lastPt.y, x, y);
            if (pt !== undefined) {
              ctx.lineTo(pt.x, pt.y);
              ctx.stroke();
            }
          }
        }
        lastPt = {'x': x, 'y': y};
        return isDrawing;
      };

      // end the drawing
      drawEnd = function drawEnd() {
        isDrawing = false;
        lastPt = undefined;
      };

      // clear the canvas
      clearDrawing = function clearDrawing(lineWidth, lineCap) {
        if (lineWidth === undefined) lineWidth = canvasLineWidth;
        if (lineCap === undefined) lineCap = canvasLineCap;

        ctx.lineWidth = lineWidth;
        ctx.lineCap = lineCap;

        ctx.strokeStyle = "rgb(0, 0, 0)";
        ctx.clearRect(0, 0, canvas.width(), canvas.height());
        if (onRedraw !== undefined) onRedraw(ctx);
      };

      self.paintWithStroke = function (strokes, lineWidth, lineCap) {
        clearDrawing(lineWidth, lineCap);

        for (var stroke_i = 0; stroke_i < strokes.length; stroke_i++) {
          for (var point_i = 0; point_i < strokes[stroke_i].length; point_i++) {
            var point = strokes[stroke_i][point_i];
            drawStroke(point.x, point.y);
          }
          drawEnd();
        }
      };

      self.dirtyImage(function () { self.paintWithStroke(self.getStrokes()); });
    })(ctx);


    var pushStroke;
    (function makeCanvasMemoryful() {
      var strokes = [];
      var future_strokes = [];

      // Define the appearance of the "undo" and "redo" links using CSS
      function styleDisableLink(link, name) {
        link
          .css({
               'color':'gray',
               'background':'url(../static/images/'+name+'-gray.png) no-repeat 2px 1px' //'background':'url(../images/'+name+'-gray.png) no-repeat 2px 1px'
               });
      }
      function styleEnableLink(link, name) {
        link
          .css({
               'color':'blue',
               'background':'url(../static/images/'+name+'.png) no-repeat 2px 1px' //'background':'url(../images/'+name+'.png) no-repeat 2px 1px'
               });
      }

      // enable and disable buttons based on whether there
      // are strokes to do and redo
      function disableUndo() { styleDisableLink(undoLink, 'undo'); }
      function enableUndo() { styleEnableLink(undoLink, 'undo'); }
      function disableRedo() { styleDisableLink(redoLink, 'redo'); }
      function enableRedo() { styleEnableLink(redoLink, 'redo'); }

      function dirtyDoButtons() {
        if (self.canUndo())
          enableUndo();
        else
          disableUndo();
        if (self.canRedo())
          enableRedo();
        else
          disableRedo();
      }
      self.dirty(dirtyDoButtons);

      self.canUndo = function canUndo() { return strokes.length > 0; };
      self.canRedo = function canRedo() { return future_strokes.length > 0; };

      self.undo = function undo() {
        if (!self.canUndo()) throw 'Error: Attempt to undo canvas ' + canvas + ' failed; no state to undo.';
        future_strokes.push(strokes.pop());
        self.dirtyImage();
      }

      self.redo = function redo() {
        if (!self.canRedo()) throw 'Error: Attempt to redo canvas ' + canvas + ' failed; no state to redo.';
        strokes.push(future_strokes.pop());
        self.dirtyImage();
      };

      self.clearFuture = function clearFuture() {
        future_strokes = [];
        self.dirty();
      };

      self.clearPast = function clearPast() {
        strokes = [];
        self.dirty();
      };

      self.clearState = function clearState() {
        self.clearFuture();
        self.clearPast();
      };

      self.getStrokes = function getStrokes() {
        return strokes.slice(0);
      };

      pushStroke = function pushStroke(stroke) {
        strokes.push(stroke);
        self.dirty();
      };
    })();

    //===================================================================
    //Canvas Drawing - From http://detexify.kirelabs.org/js/canvassify.js
    // make a canvas drawable and give the stroke to some function after each stroke
    // better canvas.drawable({start: startcallback, stop: stopcallback, stroke: strokecallback})
    //function makeDrawable(canvas, lineWidth, undoLink, redoLink) {
    (function (ctx, canvasLineWidth, canvasLineCap) {
      // Initilize canvas context values
      ctx.lineWidth = canvasLineWidth;
      ctx.lineCap = canvasLineCap;
      //end initilization
      var is_stroking = false;
      var has_drawn = false;
      var current_stroke;
      function point(x, y) {
        return {"x":x, "y":y, "t": (new Date()).getTime()};
      }

      // start recording the stroke
      var start = function start(evt) {
        is_stroking = true;
        var coords = getMouseCoordsWithinTarget(evt);
        has_drawn = drawStroke(coords.x, coords.y);
        current_stroke = [point(coords.x, coords.y)];
        // initialize new stroke
      };

      // record a movement event
      var stroke = function stroke(evt) {
        if (is_stroking) {
          var coords = getMouseCoordsWithinTarget(evt);
          has_drawn = drawStroke(coords.x, coords.y) || has_drawn; // drawStroke returns true if we actually draw this stroke.  reverse the order to make it so drawStroke is always called.
          current_stroke.push(point(coords.x, coords.y));
        }
      };

      // stop recording a stroke
      var stop = function stop(evt) {
        drawEnd();
        if (is_stroking && has_drawn) {
          pushStroke(current_stroke);
          self.clearFuture();
        }
        is_stroking = false;
      };

      // define how to handle each mouse event
      canvas
        .mousedown(start) // start stroke
        .mousemove(stroke) // record movement
        .mouseup(stop) // end stroke when mouse-up
        .mouseout(stop); // end stroke when you  move off the canvas
    })(ctx, canvasLineWidth, canvasLineCap);

    // clear the canvas
    self.clear = function clear(doRedraw) {
      self.clearState();
      ctx.strokeStyle = "rgb(0, 0, 0)";
      ctx.clearRect(0, 0, canvas.width(), canvas.height());
      if (onRedraw !== undefined && (doRedraw || doRedraw === undefined))
        onRedraw(ctx);
      self.dirtyImage();
    }
    self.clear(false);

    //===================================================================

    // return a data:URL containing a representation of the image as a PNG
    this.getImage = function getImage() {
      return canvas[0].toDataURL();
    };

    // Print the trajectory of the entire motor trace
    this.strokesToString = function (extraDelimiter) {
      if (extraDelimiter === undefined) extraDelimiter = '';
      var cur_stroke;
      var rtn = '[';
      var strokes = self.getStrokes();
      for (var j = 0; j < strokes.length; j++) {
        rtn += '[';
        cur_stroke = strokes[j];
        for (var k = 0; k < cur_stroke.length; k++) {
          rtn += "{'x':" + cur_stroke[k].x + ",'y':" + cur_stroke[k].y + ",'t':" + cur_stroke[k].t + '}'
            rtn += (k + 1 == cur_stroke.length ? '' : ','+extraDelimiter);
        }
        rtn += ']' + (j + 1 == strokes.length ? '' : ','+extraDelimiter);
      }
      return rtn + ']';
    };

    this.height = function height() { return self.canvas.height(); };
    this.width = function width() { return self.canvas.width(); };

    return this;
  };

})(1, 'butt', jQuery, jQuery); // default parameters

//From http://skuld.bmsc.washington.edu/~merritt/gnuplot/canvas_demos/
function getMouseCoordsWithinTarget(event)
{
	var coords = { x: 0, y: 0};

	if(!event) // then we're in a non-DOM (probably IE) browser
	{
		event = window.event;
		if (event) {
			coords.x = event.offsetX;
			coords.y = event.offsetY;
		}
	}
	else		// we assume DOM modeled javascript
	{
		var Element = event.target ;
		var CalculatedTotalOffsetLeft = 0;
		var CalculatedTotalOffsetTop = 0 ;

		while (Element.offsetParent)
 		{
 			CalculatedTotalOffsetLeft += Element.offsetLeft ;
			CalculatedTotalOffsetTop += Element.offsetTop ;
 			Element = Element.offsetParent ;
 		}

		coords.x = event.pageX - CalculatedTotalOffsetLeft ;
		coords.y = event.pageY - CalculatedTotalOffsetTop ;
	}

	return coords;
}
