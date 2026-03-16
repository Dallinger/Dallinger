var BrowserSyncPlugin = require('browser-sync-webpack-plugin');
var path = require('path');
var env = process.env.WEBPACK_ENV;
var isProductionBuild = env === 'build';

var plugins = [];

if (!isProductionBuild) {
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
  mode: isProductionBuild ? 'production' : 'development',
  entry: {
    tracker: './dallinger/frontend/static/scripts/tracking/load-tracker.js'
  },
  output: {
    path: path.resolve(__dirname, 'dallinger/frontend/static'),
    filename: 'scripts/[name].js'
  },
  optimization: {
    minimize: isProductionBuild
  },
  devtool: 'source-map',
  plugins: plugins
};
