var webpack = require('webpack');
var BrowserSyncPlugin = require('browser-sync-webpack-plugin');
var UglifyJsPlugin = webpack.optimize.UglifyJsPlugin;
var env = process.env.WEBPACK_ENV;

var plugins = [];

if (env === 'build') {
  // uglify code for production
  plugins.push(new UglifyJsPlugin({sourceMap: true}));
} else {
  plugins.push(new BrowserSyncPlugin({
    host: 'localhost',
    port: 6001,
    proxy: {
      target: 'http://localhost:5000',
      ws: true
    },
    serveStatic: [{
      route: '/static',
      dir: 'dallinger/frontend/static'
    }]
  }));
}

module.exports = {
  entry: {
    tracker: './dallinger/frontend/static/scripts/tracking/load-tracker.js'
  },
  output: {
    path: __dirname + '/dallinger/frontend/static/',
    filename: 'scripts/[name].js'
  },
  devtool: 'source-map',
  plugins: plugins
};
