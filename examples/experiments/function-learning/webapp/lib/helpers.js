// Shuffles an array using the Fisher-Yates algorithm; not in place.
shuffle = function(array) {
  tempArray = array.slice();
  var counter = tempArray.length, temp, index;
    while (counter--) {
      index = (Math.random() * (counter + 1)) | 0;
      temp = tempArray[counter];
      tempArray[counter] = tempArray[index];
      tempArray[index] = temp;
    }
  return tempArray;
};

// Simple range from A to B: [A, A+1, A+2, ..., B]
range = function(A,B) {
  var theRange = [];
  for (var i = 0; i < B-A+1; i++) {
    theRange[i] = A+i;
  }
  return theRange;
};

bounds = function(N,min,max) {
  return Math.min(Math.max(min, N), max);
};

// Returns a random subset of N items from lst, in random order
randomSubset = function(lst,N) {
  return shuffle(lst).slice(0,N);
};

// Throw an exception if the condition does not hold.
assert = function(condition, message) {
  if (!condition) {
    throw message || "Assertion failed";
  }
};

// Adds a method to arrays that returns the difference w/r/t an input array.
Array.prototype.diff = function(a) {
  return this.filter(function(i) {return (a.indexOf(i) < 0);});
};

// Sorts the array in the order given by the input array
Array.prototype.sortByIndices = function(order) {
  var result = [];
  for(var i=0; i<this.length; i++) {
    result[i] = this[order[i]];
  }
  return result;
};

now = function() {
  return new Date().valueOf();
};
