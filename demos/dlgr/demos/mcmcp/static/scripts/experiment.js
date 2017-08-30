var my_node_id;

// Create the agent.
create_agent = function() {
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
      get_infos();
    })
    .fail(function () {
      dallinger.goToPage('questionnaire');
    });
};

get_infos = function() {
  reqwest({
    url: "/node/" + my_node_id + "/infos",
    method: 'get',
    type: 'json',
    success: function (resp) {
      sides_switched = Math.random() < 0.5;

      if (resp.infos[0].id > resp.infos[1].id) {
        animal_0 = JSON.parse(resp.infos[0].contents);
        animal_1 = JSON.parse(resp.infos[1].contents);
      } else {
        animal_0 = JSON.parse(resp.infos[1].contents);
        animal_1 = JSON.parse(resp.infos[0].contents);
      }

      if (sides_switched === false) {
        drawAnimal(animal_0, "left");
        drawAnimal(animal_1, "right");
      } else {
        drawAnimal(animal_1, "left");
        drawAnimal(animal_0, "right");
      }
      $(".submit-response").attr('disabled',false);
    },
    error: function (err) {
      console.log(err);
      errorResponse = JSON.parse(err.response);
      $('body').html(errorResponse.html);
    }
  });
};

submit_response = function(choice) {
  if (sides_switched === true) {
    choice = 1 - choice;
  }
  $(".submit-response").attr('disabled',true);
  paper.clear();

  reqwest({
    url: "/choice/" + my_node_id + "/" + choice,
    method: 'post',
    success: function (resp) {
      create_agent();
    },
    error: function (resp) {
      create_agent();
    }
  });
};

//
// Draw the animal..
//
drawAnimal = function (animal, side) {
  PPU = 50;

  if (side === "left") {
    xShift = 0;
  } else if (side === "right") {
    xShift = 200;
  }

  // Display parameters.
  shoulderJointX = 175 + xShift;
  shoulderJointY = 175;
  bodyLength = 1;

  // Stimulus parameters, convert to pixels and radians.
  bodyHeightPx = animal.body_height * PPU;
  footSpreadPx = animal.foot_spread * PPU;
  neckAngleRad = (animal.neck_angle + 90) * (Math.PI / 180);
  neckLengthPx = animal.neck_length * PPU;
  headAngleRad = animal.head_angle * -1 * (Math.PI / 180) + neckAngleRad;
  headLengthPx = animal.head_length * PPU;
  bodyTiltRad = animal.body_tilt * (Math.PI / 180);
  bodyLengthPx = bodyLength * PPU;
  tailAngleRad = (animal.tail_angle - 90) * (Math.PI / 180);
  tailLengthPx = animal.tail_length * PPU;

  // Draw the first front leg, which points forward.
  frontLeg1 = paper.path("M" + shoulderJointX + "," + shoulderJointY + "L" + (shoulderJointX - footSpreadPx/2) + "," + (shoulderJointY + bodyHeightPx));
  frontLeg1.attr("stroke-width", "2");

  // Draw the second front leg, which points backward.
  frontLeg2 = paper.path("M" + shoulderJointX + "," + shoulderJointY + "L" + (shoulderJointX + footSpreadPx/2) + "," + (shoulderJointY + bodyHeightPx));
  frontLeg2.attr("stroke-width", "2");

  // Draw the neck.
  neckX = Math.cos(neckAngleRad) * neckLengthPx;
  neckY = Math.sin(neckAngleRad) * neckLengthPx;
  neck = paper.path("M" + shoulderJointX + "," + shoulderJointY + "l" + neckX + "," + neckY);
  neck.attr("stroke-width", "2");

  // Draw the head.
  headX = Math.cos(headAngleRad) * headLengthPx;
  headY = Math.sin(headAngleRad) * headLengthPx;
  head = paper.path("M" + (shoulderJointX + neckX) + "," + (shoulderJointY + neckY) + "l" + headX + "," + headY);
  head.attr("stroke-width", "2");

  // Draw the body.
  bodyX = Math.cos(bodyTiltRad) * bodyLengthPx;
  bodyY = Math.sin(bodyTiltRad) * bodyLengthPx;
  body = paper.path("M" + shoulderJointX + "," + shoulderJointY + "l" + bodyX + "," + bodyY);
  body.attr("stroke-width", "2");

  // Draw the first back leg, which points forward.
  backLeg1 = paper.path("M" + (shoulderJointX + bodyX) + "," + (shoulderJointY + bodyY) + "l" + (-1 * footSpreadPx / 2) + "," + Math.max((bodyHeightPx - bodyY), 0));
  backLeg1.attr("stroke-width", "2");

  // Draw the second back leg, which points backward.
  backLeg2 = paper.path("M" + (shoulderJointX + bodyX) + "," + (shoulderJointY + bodyY) + "l" + footSpreadPx / 2 + "," + Math.max((bodyHeightPx - bodyY), 0));
  backLeg2.attr("stroke-width", "2");

  // Draw the tail.
  tailX = Math.cos(tailAngleRad) * tailLengthPx;
  tailY = Math.sin(tailAngleRad) * tailLengthPx;
  tail = paper.path("M" + (shoulderJointX + bodyX) + "," + (shoulderJointY + bodyY) + "l" + tailX + "," + tailY);
  tail.attr("stroke-width", "2");
};
