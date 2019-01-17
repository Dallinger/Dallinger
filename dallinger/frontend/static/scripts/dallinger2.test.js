const store = require('./store+json2.min');
global.store = store;

// Mock out alert to the command line, so we can see errors
global.window.alert = console.log;

function Fingerprint2() {
    // This mocks out Fingerprint2 
    function get() {
      return "testing";
    };
    return {"get": get};
  }
global.window.Fingerprint2 = Fingerprint2;

const dlgr = require('./dallinger2').dallinger;



test('Passes adblock check', () => {
    expect(dlgr.missingFingerprint()).toBe(false);
});

test('Storage is available', () => {
  expect(dlgr.storage.available).toBe(true);
  expect(dlgr.storage.get('foo')).toBe(undefined);
  dlgr.storage.set('foo', 'bar');
  expect(dlgr.storage.get('foo')).toBe('bar');
});