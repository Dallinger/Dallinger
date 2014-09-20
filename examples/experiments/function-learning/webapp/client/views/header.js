Template.header.isTestingPhase = function () {
    return Session.get("trialsCompleted") >= Session.get("N")/2;
};

Template.header.thisTrial = function () {
    N = Session.get("N");
    trialIndex = bounds(Session.get("trialsCompleted"), 0, N);
    if(trialIndex < N/2)
        return trialIndex + 1;
    else
        return bounds(trialIndex + 1 - N/2, 0, N/2);
};

Template.header.numTrials = function () {
    trialIndex = bounds(Session.get("trialsCompleted"), 0, N);
    if (trialIndex < 0)
        return "<loading>";
    else
        return Session.get("N")/2;
};
