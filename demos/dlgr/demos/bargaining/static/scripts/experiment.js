/*globals $, dallinger */

// The instructions page creates the participant and their node. The pair's
// session starts once both players have a node, so the game page only joins it,
// and can be reloaded safely.
var join_pair = function () {
  dallinger.createParticipant().done(function () {
    dallinger.createAgent()
      .done(function () {
        dallinger.goToPage('experiment');
      })
      .fail(function (rejection) {
        // A 403 means every pair is full
        if (rejection.status === 403) {
          dallinger.goToPage('questionnaire');
        } else {
          dallinger.error(rejection);
        }
      });
  });
};

var cents = function (price) {
  return price === null ? 'none' : price + '¢';
};

var describe_role = function (view) {
  if (view.role === 'seller') {
    return 'You are the seller. Your cost is ' + cents(view.value) +
      ', and a deal earns you the price minus your cost.';
  }
  return 'You are the buyer. Your value is ' + cents(view.value) +
    ', and a deal earns you your value minus the price.';
};

var describe_result = function (reason, view) {
  // A page that joins after the game has ended gets no view
  if (view === null) {
    return 'This game is over.';
  }
  if (view.deal !== null) {
    return 'Deal at ' + cents(view.deal) + '. You earn ' + cents(view.earnings) +
      '. The other player\'s ' + (view.role === 'seller' ? 'value' : 'cost') +
      ' was ' + cents(view.their_value) + '.';
  }
  if (reason === 'finished') {
    return 'Time ran out with no deal, so neither of you earns anything.';
  }
  return 'The game was stopped before you reached a deal.';
};

var play_bargain = function () {
  dallinger.joinRealtimeSession('bargain').done(function (socket) {
    var latest = null;

    $('#waiting').hide();
    $('#game').show();

    socket.onView(function (view) {
      latest = view;
      $('#role').text(describe_role(view));
      $('#my-offer').text(cents(view.my_offer));
      $('#their-offer').text(cents(view.their_offer));
      $('#accept').toggle(view.their_offer !== null);
      $('#offers').empty();
      view.offers.forEach(function (offer) {
        $('#offers').append($('<li>').text(
          (offer.by === view.role ? 'You' : 'They') + ' offered ' +
          cents(offer.price) + ' at ' + Math.floor(offer.time) + ' seconds'
        ));
      });
    });

    $('#offer-form').on('submit', function (event) {
      event.preventDefault();
      $('#error').text('');
      socket.send('bargain', {offer: Number($('#price').val())});
    });

    // Name the price being accepted, so the game can refuse it if the
    // other player has just changed their offer
    $('#accept').on('click', function () {
      $('#error').text('');
      socket.send('bargain', {accept: latest.their_offer});
    });

    socket.onRejected(function (number, reason) {
      $('#error').text('That didn\'t count: ' + reason + '.');
    });

    var timer = setInterval(function () {
      var now = socket.sessionTime();
      if (now !== null && latest !== null) {
        $('#timer').text(Math.ceil(Math.max(0, latest.deadline - now)));
      }
    }, 250);

    socket.onEnded(function (reason, view) {
      clearInterval(timer);
      $('#offer-form, #accept').hide();
      $('#timer').text(0);
      $('#result').text(describe_result(reason, view));
    });

    // Move on once the outcome is saved, so the bonus can be paid from it
    socket.resultSaved().done(function () {
      $('#continue').show();
    });
    $('#continue').on('click', function () {
      dallinger.goToPage('questionnaire');
    });
  }).fail(function (code, reason) {
    $('#waiting').text('Couldn\'t join the game: ' + reason);
  });
};
