# Dallinger Participant Status Synchronization

Different recruitment systems offer different levels of support for receiving
status updates about participants.

Amazon MTurk is most helpful here, because the platform sends SNS notifications
about participants who return or abandon HITs **before** they recruit
replacements, so the experiment can update state (failing nodes of abandoned
participants and freeing network positions, for example) before new participants
arrive.

Prolific, on the other hand, sends replacement participants immediately with no
notifications (there is a currently a notification system in beta status). We
work around this by periodically polling the recruitment services for status
updates when necessary.

This polling takes two forms. In the first case, we poll every N (currently 30)
seconds based on a clock task:

```mermaid
sequenceDiagram
title Clock-triggered sync

participant c as clock
participant rec_mod as recruiters
participant rec as Recruiter
participant w as worker_events
participant evt as SomeEventType
participant part as Participant
participant ex as Experiment

loop every 30 seconds
    c-)rec_mod: run_status_check (async)
end

Note over rec_mod: build dict of recruiter nicknames to particpants
loop for each recruiter
    rec_mod->>rec: verify_status_of(participants)
end

loop for each problem participant
    rec-)w: worker_event([EventType], *args) (async)
    w->>evt: __call__()
    evt->>part: end_time
    evt->>part: status
    evt->>ex: assignment_abandoned() etc.
end
```

In the second case, we allow the experiment to trigger a poll whenever a new
participant is assigned to a node, or according to some other rule of the
experimentor's choosing:

```mermaid
sequenceDiagram
title Experiment requests participant status sync

participant ex as Experiment
participant rec_mod as recruiters
participant rec as Recruiter
participant w as worker_events
participant evt as SomeEventType
participant part as Participant

ex-)rec_mod: run_status_check (async)

Note over rec_mod: build dict of recruiter nicknames to particpants
loop for each recruiter
    rec_mod->>rec: verify_status_of(participants)
end

loop for each problem participant
    rec-)w: worker_event([EventType], *args) (async)
    w->>evt: __call__()
    evt->>part: end_time
    evt->>part: status
    evt->>ex: assignment_abandoned() etc.
end
```
