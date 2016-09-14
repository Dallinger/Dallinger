//
// My jQuery extensions
//

// Detect if a jQuery select returns empty
// 
// Used like:
// $("#notAnElement").exists();
$.fn.exists = function () {
    return this.length !== 0;
}

// Used like:
// $(".myclass").get_attr('id');
// returns an array of all of the ids
$.fn.get_attr = function (myattr) {
	var out = new Array();
	this.each( function () {
		out.push($(this).attr(myattr));
	});
	return out;	
}

//
// Other extensions
//

// Crockford's method for calling super-functions
// in inheritance hierarchy
Function.prototype.method = function (name, func) {
    this.prototype[name] = func;
    return this;
};

Object.method('superior', function (name) {
    var that = this;
    var method = that[name];
    if (method === undefined) {
    	return undefined;
    	//throw new Error('Superior method .' + name + ' is undefined');	
    }
    return function () {
        return method.apply(that, arguments);
    };
});

// returns only the unique elements of an array
Array.prototype.unique = function() {
   var u = {}, a = [];
   for(var i = 0, l = this.length; i < l; ++i){
      if(u.hasOwnProperty(this[i])) {
         continue;
      }
      a.push(this[i]);
      u[this[i]] = 1;
   }
   return a;  
};