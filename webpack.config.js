const path = require('path');
const TerserPlugin = require('terser-webpack-plugin');
const BrowserSyncPlugin = require('browser-sync-webpack-plugin');
const env = process.env.WEBPACK_ENV;

const plugins = [];

if (env !== 'build') {
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
  mode: env === 'build' ? 'production' : 'development',
  entry: {
    tracker: './dallinger/frontend/static/scripts/tracking/load-tracker.js'
  },
  output: {
    path: path.join(__dirname, 'dallinger/frontend/static'),
    filename: 'scripts/[name].js'
  },
  devtool: 'source-map',
  optimization: {
    minimize: env === 'build',
    minimizer: [
      new TerserPlugin({
        terserOptions: {
          sourceMap: true
        }
      })
    ]
  },
  plugins: plugins
};
