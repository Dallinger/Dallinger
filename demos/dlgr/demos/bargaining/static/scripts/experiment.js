/*globals $, dallinger */

// How long the page waits for the next round before letting the player move
// on. The next round is normally there before the last one's result is saved.
var NEXT_ROUND_WAIT_MS = 10000;

// --- Called from the templates ---

// The instructions page creates the participant and their node. The pair's
// first round starts once both players have a node, so the game page only
// joins it, and can be reloaded during a round.
var joinPair = function () {
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

var playBargain = function (settings) {
  // The current round's socket and latest view. The controls below are set
  // up once and act on whichever round is being played.
  var socket = null;
  var latest = null;

  $('#offer-form').on('submit', function (event) {
    event.preventDefault();
    var price = $('#price').val();
    if (price === '') {
      $('#error').text('Enter a price in cents.');
      return;
    }
    $('#error').text('');
    socket.send('bargain', {offer: Number(price)});
  });

  // Name the price being accepted, so the game can refuse it if the other
  // player has just changed their offer
  $('#accept').on('click', function () {
    $('#error').text('');
    socket.send('bargain', {accept: latest.their_offer});
  });

  // Chat goes to the experiment, which saves it and sends it to both players,
  // so a player's own message appears once it's saved
  $('#chat-form').on('submit', function (event) {
    event.preventDefault();
    var text = $('#chat-text').val().trim();
    if (text === '' || socket === null) {
      return;
    }
    socket.send('bargain_chat', {
      participant_id: dallinger.identity.participantId,
      session: socket.session,
      text: text
    });
    $('#chat-text').val('');
  });

  $('#continue').on('click', function () {
    dallinger.goToPage('questionnaire');
  });

  var moveOn = function () {
    $('#next-round').hide();
    $('#continue').show();
  };

  var playRound = function (afterSession) {
    var joining = joinBargain(settings.chat, afterSession);
    // A next round that doesn't come means the round count is off, as after
    // a reload with sessionStorage turned off
    var fallback = afterSession === undefined ? null : setTimeout(function () {
      joining.cancel();
      moveOn();
    }, NEXT_ROUND_WAIT_MS);
    joining.done(function (joined) {
      clearTimeout(fallback);
      var ended = false;
      var round = roundOf(joined.session);
      socket = joined;
      latest = null;

      $('#waiting, #next-round').hide();
      $('#game, #offer-form').show();
      $('#round').text('Round ' + round + ' of ' + settings.rounds).toggle(settings.rounds > 1);
      $('#offers').empty();
      $('#price').val('');
      $('#error, #result').text('');
      $('#chat-form :input').prop('disabled', false);
      if (settings.rounds > 1) {
        $('#chat-log').append($('<li class="text-muted">').text('Round ' + round));
      }

      socket.onView(function (view) {
        latest = view;
        $('#role').text(describeRole(view));
        $('#my-offer').text(cents(view.my_offer));
        $('#their-offer').text(cents(view.their_offer));
        // The final view can arrive after onEnded
        $('#accept').toggle(!ended && view.their_offer !== null);
        $('#offers').empty();
        view.offers.forEach(function (offer) {
          $('#offers').append($('<li>').text(
            (offer.by === view.role ? 'You' : 'They') + ' offered ' +
            cents(offer.price) + ' ' + describeTime(offer, view)
          ));
        });
      });

      socket.onRejected(function (number, reason) {
        $('#error').text('That didn\'t count: ' + reason + '.');
      });

      if (settings.chat) {
        // Shows every message, even one from the round before or after, since
        // the two pages reach a new round at slightly different times
        socket.onDirect(function (message) {
          var who = String(message.from) === String(dallinger.identity.participantId) ? 'You' : 'They';
          $('#chat-log').append($('<li>').text(who + ': ' + message.text));
        });
      }

      var timer = setInterval(function () {
        var now = socket.sessionTime();
        if (now === null || latest === null) {
          return;
        }
        // The deadline is null until both players are here
        var waiting = latest.deadline === null;
        $('#clock-waiting').toggle(waiting);
        $('#time-left').toggle(!waiting);
        if (!waiting) {
          $('#timer').text(Math.ceil(Math.max(0, latest.deadline - now)));
        }
      }, 250);

      socket.onEnded(function (reason, view) {
        ended = true;
        clearInterval(timer);
        $('#clock-waiting').hide();
        $('#time-left').show();
        $('#offer-form, #accept').hide();
        $('#chat-form :input').prop('disabled', true);
        $('#timer').text(0);
        $('#result').text(describeResult(reason, view));
        // The next round starts a moment after this one ends, so each result
        // is also kept in a list the player can still read
        if (settings.rounds > 1) {
          $('#earlier').show();
          $('#history').append($('<li>').text('Round ' + round + ': ' + describeResult(reason, view)));
        }
      });

      // Move on once the outcome is saved, so the bonus can be paid from it.
      // Another round follows only a deal or time running out, the endings
      // Dallinger calls "finished", and by now it has been saved. Any other
      // ending, or a failed wait, ends the series.
      joined.resultSaved().done(function (result) {
        var another = result.status === 'ended' && result.reason === 'finished';
        if (another && round < settings.rounds) {
          joined.close();
          $('#next-round').show();
          playRound(joined.session);
        } else {
          moveOn();
        }
      }).fail(moveOn);
    }).fail(function (code, reason) {
      $('#waiting').text('Couldn\'t join the game: ' + reason).show();
    });
  };

  playRound();
};

// --- Game helpers ---

// Join the pair's next round, the first one or the one after afterSession,
// and resolve with its socket. With chat on, the page joins on the /chat
// route, so the same socket can also send chat. The promise's cancel method
// stops waiting.
var joinBargain = function (chat, afterSession) {
  var options = {afterSession: afterSession};
  if (!chat) {
    return dallinger.joinRealtimeSession('bargain', options);
  }
  var waiting = dallinger.waitForRealtimeSession('bargain', options);
  var joining = waiting.then(function (sessionId) {
    return dallinger.openChatSocket({session: sessionId, gameChannel: 'bargain'});
  });
  joining.cancel = waiting.cancel;
  return joining;
};

// Which round a session is. The count is kept in the tab's sessionStorage, so
// a reloaded page still shows the right round number.
var roundOf = function (sessionId) {
  var key = 'bargaining-round-' + dallinger.identity.participantId;
  var saved = null;
  try {
    saved = JSON.parse(window.sessionStorage.getItem(key));
  } catch (error) {
    // Storage can be turned off, and then a reload counts from 1 again
  }
  var round = 1;
  if (saved !== null) {
    round = saved.session === sessionId ? saved.round : saved.round + 1;
  }
  try {
    window.sessionStorage.setItem(key, JSON.stringify({session: sessionId, round: round}));
  } catch (error) {}
  return round;
};

var cents = function (price) {
  return price === null ? 'none' : price + '¢';
};

var describeRole = function (view) {
  if (view.role === 'seller') {
    return 'You are the seller. Your cost is ' + cents(view.value) +
      ', and a deal earns you the price minus your cost.';
  }
  return 'You are the buyer. Your value is ' + cents(view.value) +
    ', and a deal earns you your value minus the price.';
};

var describeResult = function (reason, view) {
  // A page reloaded just after a round ended gets no view
  if (view === null) {
    return 'This round is over.';
  }
  if (view.deal !== null) {
    return 'Deal at ' + cents(view.deal) + '. You earn ' + cents(view.earnings) +
      '. The other player\'s ' + (view.role === 'seller' ? 'value' : 'cost') +
      ' was ' + cents(view.their_value) + '.';
  }
  if (reason === 'finished') {
    return 'Time ran out with no deal, so neither of you earns anything.';
  }
  return 'The round was stopped before you reached a deal.';
};

// When an offer was made, counting from the start of the round's clock
var describeTime = function (offer, view) {
  if (view.started === null || offer.time < view.started) {
    return 'before the clock started';
  }
  return 'at ' + Math.floor(offer.time - view.started) + ' seconds';
};
