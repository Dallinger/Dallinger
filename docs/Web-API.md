The Wallace server comes with a number of pre-existing routes by which the front-end can communicate with the back end. Many of these routes correspond to specific functions of Wallace's [classes](https://github.com/suchow/Wallace/wiki/Classes), particularly Node.

#### Miscellaneous routes

**/ad_address/\<mode>/\<hit_id>** [get]   
Used to get the address of the experiment on the psiTurk server and to return participants to MTurk upon completion of the experiment. This route is pinged automatically by the function `submit_assignment` in wallace.js.

**/\<directory>/\<page>** [get]   
Returns the html page with the name \<page> from the directory called \<directory>.

**/summary** [get]   
Returns a summary of the statuses of Participants.

**/\<page>** [get]   
Returns the html page with the name \<page>.

#### Experiment routes

**/experiment_property/\<property>** [get]   
Returns the value of the requested property as a json `response.<prop>`.

**/launch** [post]   
Initializes the experiment and opens recruitment. This route is automatically pinged by Wallace.

**/network/\<network_id>** [get]   
Returns a json description of the requested network as `response.network`.

**/participant/\<participant_id>** [get]   
Returns a json description of the requested participant as `response.participant`.

**/participant/\<worker_id>/\<hit_id>/\<assignment_id>/\<mode>** [post]   
Create a participant. Returns a json description of the participant as `response.participant`.

