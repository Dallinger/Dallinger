# Dallinger Task Submission and Completion

A mermaid syntax diagram of task completion and subsequent triggered execution paths.

```mermaid
sequenceDiagram
title Dallinger Assignment Submission

actor hw as HIT win
actor ew as EXP win
participant d2 as dallinger2
participant es as experiment_server
participant part as Participant

participant ex as Experiment
participant rec as Recruiter
participant wf as worker_function
participant nt as Notification
participant sub as RecruiterSubmissionComplete


ew->>d2: submitQuestionnaire()
d2->>es: /question/<participant ID>
es-->>d2: HTTP Response
d2->>d2: submitAssignment()
d2->>es: /worker_complete POST
es->>part: end_time
es->>ex: participant_task_completed()
ex->>rec: assign_experiment_qualifications()
es->>rec: on_task_completion()
rec-->>es: {"new_status": (status), "action": (event name)}
es->>part: status
note over es: COMMIT
opt "action" requested by recruiter (synchronous recruiters)
es->>wf: __call__("RecruiterSubmissionComplete", args...)
end

es-->>d2: HTTP Response
d2-->>hw: location=/recruiter-exit
hw->>es: /recruiter-exit GET
es->>rec: exit_response(experiment=exp, participant=participant)
alt synchronous recruiters
rec-->>es: <rendered template specific to Recruiter>
es-->>hw: <rendered template specific to Recruiter>
else asynchronous recruiters
rec-->>es: <rendered template specific to Recruiter>
es-->>hw: <rendered template specific to Recruiter>
hw->>rec: /prolific-submission-listener POST (Recruiter-specific route)
rec->>part: status="submitted"
note over rec: COMMIT
rec-)wf: ASYNC __call__("RecruiterSubmissionComplete", args...) (see below)

rec-->>d2: HTTP Response
d2->>hw: location=prolificStudySubmissionURL
end

note over rec: Later, resuming call from Recruiter...
rec-)wf: __call__("RecruiterSubmissionComplete", args...)
wf->>nt: (add Note to DB)
note over wf: COMMIT
wf->>sub: __call__()
sub->>ex: on_recruiter_submission_complete(participant)
note over ex: Most of what follows becomes potentially private to the Experiment:
opt if not set already
ex->>part: end_time
end

ex->>rec: approve_hit(assignment_id)
ex->>part: base_pay


ex->>ex: data_check()
ex-->>ex: bool
alt happy path
ex->>ex: bonus
ex-->>ex: $2.99
ex->>part: bonus=2.99
ex->>ex: bonus_reason()
ex-->>ex: "Great work"
ex->>rec: award_bonus()
else sad path
ex->>part: status="bad_data"
ex->>ex: data_check_failed()
ex->>rec: recruit(n=1)
end


ex->>ex: attention_check()
ex-->>ex: bool
alt happy path
ex->>part: status="approved"
ex->>ex: submission_successful()
ex->>ex: recruit()

else sad path
ex->>part: status="did_not_attend"
ex->>rec: close_recruitment() ??
ex->>ex: attention_check_failed()
ex->>rec: recruit(n=1)
end
note over wf: COMMIT
```