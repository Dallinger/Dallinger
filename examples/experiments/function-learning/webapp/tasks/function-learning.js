// Settings.
xMax = 100;

/*
Define the functions available for the function learning experiment.
*/

// Linear function.
f1 = function (x) {
  return x;
}

// Negative linear function.
f2 = function (x) {
  return 101 - x;
}

// Nonlinear U-shaped function.
f3 = function (x) {
  return 50.5 + 49.5 * Math.sin(Math.PI/2 + x/(5*Math.PI))
}

// Random one-to-one pairing.
f4Order = shuffle(range(1,xMax));
f4 = function (x) {
  return f4Order[x-1]; // Javascript uses zero indexing
}
