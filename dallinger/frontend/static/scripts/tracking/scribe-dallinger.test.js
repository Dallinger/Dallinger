const {ScribeDallingerTracker} = require('./scribe-dallinger');

describe('ScribeDallingerTracker', function () {
  var request;

  beforeEach(function () {
    request = {headers: {}};
    global.XMLHttpRequest = jest.fn(function () {
      this.addEventListener = jest.fn();
      this.open = (method, url) => { request.url = url; };
      this.setRequestHeader = (name, value) => { request.headers[name] = value; };
      this.send = (data) => { request.details = JSON.parse(data.get('details')); };
    });
    window.dallinger = {
      PARTICIPANT_TOKEN_HEADER: 'X-Dallinger-Participant-Token',
      identity: {participantToken: 'secret'},
    };
    window.dlgr.node_id = 3;
  });

  function track(value) {
    ScribeDallingerTracker({base_url: 'http://localhost/'})
      .tracker({path: '/events/scroll', value: value});
  }

  test('sends the participant token to /info', () => {
    track({});
    expect(request.url).toBe('http://localhost/info/3');
    expect(request.headers).toEqual({'X-Dallinger-Participant-Token': 'secret'});
  });

  test('leaves the token out of the URLs it records', () => {
    var query = () => ({participant_token: 'secret', page: '2'});
    track({source: {url: {query: query()}}, target: {url: {query: query()}}});
    expect(request.details.source.url.query).toEqual({page: '2'});
    expect(request.details.target.url.query).toEqual({page: '2'});
  });
});
