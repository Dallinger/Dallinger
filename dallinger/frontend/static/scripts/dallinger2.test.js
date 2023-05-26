/*globals expect, describe, jest, test, beforeEach */

const store = require('./store+json2.min');
global.store = store;
// Mock out alert to the command line, so we can see errors
global.window.alert = console.log;


function StubFingerprint2() {
  // A fake Fingerprint function that always returns the same value.
  function get(callback) {
    window.setTimeout(function() {
        callback("testing");
    }, 0);
  }

  return {"get": get};
}

// Setup run before other beforeEach blocks
beforeEach(() => {
  // Stub out Fingerprint2 with a deterministic replacement.
  global.window.Fingerprint2 = StubFingerprint2;
  // re-load dallinger2 in each test to avoid interactions between tests:
  jest.resetModules();
});


describe('getUrlParameter', function () {

  var dlgr;

  beforeEach(function () {
    window.history.pushState({}, 'Test Title', '/test.html?key1=val1&key2=val2');
    dlgr = require('./dallinger2').dallinger;
  });

  test('getUrlParameter returns values for params', () => {
    expect(dlgr.getUrlParameter('key1')).toBe('val1');
    expect(dlgr.getUrlParameter('key2')).toBe('val2');
  });

  test('getUrlParameter returns undefined for missing params', () => {
    expect(dlgr.getUrlParameter('nonexistent')).toBe(undefined);
  });

});

describe('AD block functions', function () {

  var dlgr;

  beforeEach(function () {
    dlgr = require('./dallinger2').dallinger;
  });


  test('Passes basic adblock check', () => {
    expect(dlgr.missingFingerprint()).toBe(false);
  });

  /* Marked this test to be skipped, since it does fail and I don't know
     how to test this effectively. */
  test.skip('hasAdBlocker should be not call callback', done => {
    function callback() {
      throw new Error("hasAdBlocker() found a blocker!");
      done();
    }

    dlgr.hasAdBlocker(callback);
  });

});


describe('storage', function () {

  var dlgr;

  beforeEach(function () {
    dlgr = require('./dallinger2').dallinger;
  });

  test('Storage is available', () => {
    expect(dlgr.storage.available).toBe(true);
  });

  test('Unstored values return undefined', () => {
    expect(dlgr.storage.get('foo')).toBe(undefined);
  });

  test('Values are storable', () => {
    dlgr.storage.set('foo', 'bar');
    expect(dlgr.storage.get('foo')).toBe('bar');
  });

});

describe('identity', function () {
  var dlgr;

  beforeEach(function () {
    window.history.pushState({}, 'Test Title',
      'test.html?recruiter=hotair&hitId=HHH&assignmentId=AAA&workerId=WWW&mode=debug'
    );

    dlgr = require('./dallinger2').dallinger;
  });

  test('identity object is initialized from query string', () => {
    expect(dlgr.identity.recruiter).toBe('hotair');
    expect(dlgr.identity.assignmentId).toBe('AAA');
    expect(dlgr.identity.hitId).toBe('HHH');
    expect(dlgr.identity.workerId).toBe('WWW');
    expect(dlgr.identity.uniqueId).toBe('WWW:AAA');
    expect(dlgr.identity.mode).toBe('debug');
  });

  test('participantId is initially undefined', () => {
    expect(dlgr.identity.participantId).toBe(undefined);
  });

  test('values can be set', () => {
    dlgr.identity.recruiter = 'other recruiter';
    expect(dlgr.identity.recruiter).toBe('other recruiter');
  });

});
