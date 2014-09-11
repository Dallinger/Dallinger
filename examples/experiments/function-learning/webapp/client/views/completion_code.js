Template.completionCode.code = function () {
    return amplify.store("agentUUID");
};

Handlebars.registerHelper("isCompleted", function() {
    return Session.get("trialsCompleted") === Session.get("N");
});
