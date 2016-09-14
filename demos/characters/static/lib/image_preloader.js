// 
// list_list_fns: list of lists of file names of images to load. Or just a single list
//
// Inputs
//   f_display_counter: function that displays the percent of images loaded (takes one argument)
//   f_on_done: function to execute when loading is done
//   f_on_error: function to excute if an image doesn't load
//
var image_preloader = function (list_list_fns,f_on_done,f_on_error,f_display_counter) {
	
	var nlist = []; // number of lists
	var ntot = 0; // number of total files
	var list_list_images = new Array(); // image objects
	var list_lengths = []; // list of lenths for each array
	var nimg_load = 0; // number of images that have loaded
	var all_done = false; // is the loading all done?
	
	// "global_count" is the global index into the images
	// returns [x y] where x is the list index (0:nlist-1) and y is the index in that list
	var compute_location = function (global_count) {
		var l = 0;
		while (global_count >= list_lengths[l]) {
			global_count -= list_lengths[l];
			l++;
		}
		var i = global_count;
		var out = new Array(l,i);
		return out;		
	};
	
	// are all the images loaded? (return true or false)
	var all_loaded = function () {
		return (nimg_load === ntot);
	};

	// recurisvely load all images in the set
	var load_next_image = function() {
		var vindx = compute_location(nimg_load);
		var l = vindx[0];
		var i = vindx[1];
		
		list_list_images[l][i] = new Image();
		list_list_images[l][i].src = list_list_fns[l][i];
		list_list_images[l][i].onload = function () {
			nimg_load++;
			var pload = Math.round(nimg_load / ntot * 100);
			if (f_display_counter !== undefined) {
				f_display_counter(pload); // excute user-supplied display function
			}
			if (!all_loaded()) {
				load_next_image();
			}
			else {
				all_done = true; // all the work is done
				if (f_on_done !== undefined) {
					f_on_done(); // execute user-supplied stop function
				}
			}			
		};
		list_list_images[l][i].onerror = function () {
			if (f_on_error !== undefined) {
				f_on_error(); // execute user-supplied function on error
			}
		};					
	};
	
	// object constructor
	(function () {
		//if (f_display_counter === undefined) {
		//	throw new Error('Preloader DISPLAY function undefined');
		//}
		//if (f_on_done === undefined) {
		//	throw new Error('Preloader DONE function undefined');
		//}
		//if (f_on_error === undefined) {
		//	throw new Error('Preloader ERROR function undefined');
		//}
		// convert a list of strings into a list of list of strings
		if (typeof list_list_fns[0] === 'string') {
			var temp = new Array();
			temp[0] = list_list_fns;
			list_list_fns = temp;
		}
		nlist = list_list_fns.length;
		// initialize loaded array to false		
		for (var l=0; l<nlist; l++) {
			list_lengths[l] = list_list_fns[l].length;
			ntot += list_lengths[l];
			list_list_images[l] = new Array();
		}
		// start the loading process
		load_next_image();						
	})();
	
	return {		
		// get the structure of loaded images
		get_images : function () {
			if (!all_done) {
				throw new Error("Should not call this until images are all loaded");
				return undefined;
			}			
			var output = list_list_images;
			if (nlist === 1) {
				output = list_list_images[0];
			}
			return output;
		},
	}
};