wallaceUrl = 'http://127.0.0.1:5000/';
Meteor.methods({
    createAgent: function () {
        this.unblock();
        return HTTP.post(wallaceUrl + "agents");
    },
    getPendingTransmissions: function (uuid) {
        this.unblock();
        url = wallaceUrl + "transmissions?destination_uuid=" + uuid;
        return HTTP.get(url);
    },
    getInfo: function (uuid) {
        this.unblock();
        url = wallaceUrl + "information/" + uuid;
        return HTTP.get(url);
    },
    createInfo: function (origin_uuid, contents) {
        this.unblock();
        url = wallaceUrl +
              "information?origin_uuid=" + origin_uuid +
              "&contents=" + contents;
        return HTTP.post(url);
    },
    allAgents: function () {
        this.unblock();
        url = wallaceUrl + "agents";
        return HTTP.get(url);
    }
});
