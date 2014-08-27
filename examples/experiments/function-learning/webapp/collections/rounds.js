// "use strict";
/* global Rounds: true, Meteor, now */

Rounds = new Meteor.Collection("Rounds");

/*
Whenever a new round is added to the database, add a timestamp. Whenever a
round is updated, adjust the completion timestamp.
*/
Rounds.deny({
  "insert": function(userId, doc) {
    doc.createdAt = now();
    return false;
  },
  "update": function (userId, doc) {
    doc.completedAt = new Date().valueOf();
    return false;
  }
});

Rounds.allow({
  "insert": function () {
    return true;
  },
  "update": function () {
    return true;
  }
});
