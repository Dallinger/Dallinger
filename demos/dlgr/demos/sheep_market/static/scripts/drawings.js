$(window).load( function(){
  $.get('drawings', function(data) {
    drawings = data['drawings'];
    for (var i = 0; i < drawings.length; i++) {
      $('#gallery').prepend('<img src="' + drawings[i].image + '" />')
    }
  });
});
