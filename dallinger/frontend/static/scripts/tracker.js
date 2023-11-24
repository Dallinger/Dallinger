/******/ (function(modules) { // webpackBootstrap
/******/ 	// The module cache
/******/ 	var installedModules = {};
/******/
/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {
/******/
/******/ 		// Check if module is in cache
/******/ 		if(installedModules[moduleId]) {
/******/ 			return installedModules[moduleId].exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = installedModules[moduleId] = {
/******/ 			i: moduleId,
/******/ 			l: false,
/******/ 			exports: {}
/******/ 		};
/******/
/******/ 		// Execute the module function
/******/ 		modules[moduleId].call(module.exports, module, module.exports, __webpack_require__);
/******/
/******/ 		// Flag the module as loaded
/******/ 		module.l = true;
/******/
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/
/******/
/******/ 	// expose the modules object (__webpack_modules__)
/******/ 	__webpack_require__.m = modules;
/******/
/******/ 	// expose the module cache
/******/ 	__webpack_require__.c = installedModules;
/******/
/******/ 	// identity function for calling harmony imports with the correct context
/******/ 	__webpack_require__.i = function(value) { return value; };
/******/
/******/ 	// define getter function for harmony exports
/******/ 	__webpack_require__.d = function(exports, name, getter) {
/******/ 		if(!__webpack_require__.o(exports, name)) {
/******/ 			Object.defineProperty(exports, name, {
/******/ 				configurable: false,
/******/ 				enumerable: true,
/******/ 				get: getter
/******/ 			});
/******/ 		}
/******/ 	};
/******/
/******/ 	// getDefaultExport function for compatibility with non-harmony modules
/******/ 	__webpack_require__.n = function(module) {
/******/ 		var getter = module && module.__esModule ?
/******/ 			function getDefault() { return module['default']; } :
/******/ 			function getModuleExports() { return module; };
/******/ 		__webpack_require__.d(getter, 'a', getter);
/******/ 		return getter;
/******/ 	};
/******/
/******/ 	// Object.prototype.hasOwnProperty.call
/******/ 	__webpack_require__.o = function(object, property) { return Object.prototype.hasOwnProperty.call(object, property); };
/******/
/******/ 	// __webpack_public_path__
/******/ 	__webpack_require__.p = "";
/******/
/******/ 	// Load entry module and return exports
/******/ 	return __webpack_require__(__webpack_require__.s = 2);
/******/ })
/************************************************************************/
/******/ ([
/* 0 */
/***/ (function(module, exports, __webpack_require__) {

/*! scribe-analytics 2017-08-30 */
!function(a){if("function"==typeof bootstrap)bootstrap("scribe",a);else if(true)module.exports=a();else if("function"==typeof define)define(a);else if("undefined"!=typeof ses){if(!ses.ok())return;ses.makeScribe=a}else window.Scribe=a()}(function(){Date.prototype.toISOString||!function(){function a(a){var b=String(a);return 1===b.length&&(b="0"+b),b}Date.prototype.toISOString=function(){return this.getUTCFullYear()+"-"+a(this.getUTCMonth()+1)+"-"+a(this.getUTCDate())+"T"+a(this.getUTCHours())+":"+a(this.getUTCMinutes())+":"+a(this.getUTCSeconds())+"."+String((this.getUTCMilliseconds()/1e3).toFixed(3)).slice(2,5)+"Z"}}(),"undefined"==typeof sessionStorage&&!function(a){function b(){function b(){k.cookie=["sessionStorage="+a.encodeURIComponent(h=f.key(128))].join(";"),i=f.encode(h,i),g=new g(d,"name",d.name)}var e,k=(d.name,d.document),l=/\bsessionStorage\b=([^;]+)(;|$)/,m=l.exec(k.cookie);if(m){h=a.decodeURIComponent(m[1]),i=f.encode(h,i),g=new g(d,"name");for(var n=g.key(),e=0,o=n.length,p={};o>e;++e)0===(m=n[e]).indexOf(i)&&(j.push(m),p[m]=g.get(m),g.del(m));if(g=new g.constructor(d,"name",d.name),0<(this.length=j.length)){for(e=0,o=j.length,c=g.c,m=[];o>e;++e)m[e]=c.concat(g._c,g.escape(n=j[e]),c,c,(n=g.escape(p[n])).length,c,n);d.name+=m.join("")}}else b(),l.exec(k.cookie)||(j=null)}var d=a;try{for(;d!==d.top;)d=d.top}catch(e){}var f=function(a,b){return{decode:function(a,b){return this.encode(a,b)},encode:function(b,c){for(var d,e=b.length,f=c.length,g=[],h=[],i=0,j=0,k=0,l=0;256>i;++i)h[i]=i;for(i=0;256>i;++i)j=(j+(d=h[i])+b.charCodeAt(i%e))%256,h[i]=h[j],h[j]=d;for(j=0;f>k;++k)i=k%256,j=(j+(d=h[i]))%256,e=h[i]=h[j],h[j]=d,g[l++]=a(c.charCodeAt(k)^h[(e+d)%256]);return g.join("")},key:function(c){for(var d=0,e=[];c>d;++d)e[d]=a(1+(255*b()<<0));return e.join("")}}}(a.String.fromCharCode,a.Math.random),g=function(a){function b(a,b,c){this._i=(this._data=c||"").length,(this._key=b)?this._storage=a:(this._storage={_key:a||""},this._key="_key")}function c(a,b){var c=this.c;return c.concat(this._c,this.escape(a),c,c,(b=this.escape(b)).length,c,b)}return b.prototype.c=String.fromCharCode(1),b.prototype._c=".",b.prototype.clear=function(){this._storage[this._key]=this._data},b.prototype.del=function(a){var b=this.get(a);null!==b&&(this._storage[this._key]=this._storage[this._key].replace(c.call(this,a,b),""))},b.prototype.escape=a.escape,b.prototype.get=function(a){var b=this._storage[this._key],c=this.c,d=b.indexOf(a=c.concat(this._c,this.escape(a),c,c),this._i),e=null;return d>-1&&(d=b.indexOf(c,d+a.length-1)+1,e=b.substring(d,d=b.indexOf(c,d)),e=this.unescape(b.substr(++d,e))),e},b.prototype.key=function(){for(var a=this._storage[this._key],b=this.c,c=b+this._c,d=this._i,e=[],f=0,g=0;-1<(d=a.indexOf(c,d));)e[g++]=this.unescape(a.substring(d+=2,f=a.indexOf(b,d))),d=a.indexOf(b,f)+2,f=a.indexOf(b,d),d=1+f+1*a.substring(d,f);return e},b.prototype.set=function(a,b){this.del(a),this._storage[this._key]+=c.call(this,a,b)},b.prototype.unescape=a.unescape,b}(a);"[object Opera]"===Object.prototype.toString.call(a.opera)&&(history.navigationMode="compatible",g.prototype.escape=a.encodeURIComponent,g.prototype.unescape=a.decodeURIComponent),b.prototype={length:0,key:function(a){if("number"!=typeof a||0>a||j.length<=a)throw"Invalid argument";return j[a]},getItem:function(a){if(a=i+a,l.call(k,a))return k[a];var b=g.get(a);return null!==b&&(b=k[a]=f.decode(h,b)),b},setItem:function(a,b){this.removeItem(a),a=i+a,g.set(a,f.encode(h,k[a]=""+b)),this.length=j.push(a)},removeItem:function(a){var b=g.get(a=i+a);null!==b&&(delete k[a],g.del(a),this.length=j.remove(a))},clear:function(){g.clear(),k={},j.length=0}};var h,i=d.document.domain,j=[],k={},l=k.hasOwnProperty;j.remove=function(a){var b=this.indexOf(a);return b>-1&&this.splice(b,1),this.length},j.indexOf||(j.indexOf=function(a){for(var b=0,c=this.length;c>b;++b)if(this[b]===a)return b;return-1}),d.sessionStorage&&(b=function(){},b.prototype=d.sessionStorage),b=new b,null!==j&&(a.sessionStorage=b)}(window);var a="undefined"==typeof a?{}:a;if(function(a){function b(a,b){var c=a[0],h=a[1],i=a[2],j=a[3];c=d(c,h,i,j,b[0],7,-680876936),j=d(j,c,h,i,b[1],12,-389564586),i=d(i,j,c,h,b[2],17,606105819),h=d(h,i,j,c,b[3],22,-1044525330),c=d(c,h,i,j,b[4],7,-176418897),j=d(j,c,h,i,b[5],12,1200080426),i=d(i,j,c,h,b[6],17,-1473231341),h=d(h,i,j,c,b[7],22,-45705983),c=d(c,h,i,j,b[8],7,1770035416),j=d(j,c,h,i,b[9],12,-1958414417),i=d(i,j,c,h,b[10],17,-42063),h=d(h,i,j,c,b[11],22,-1990404162),c=d(c,h,i,j,b[12],7,1804603682),j=d(j,c,h,i,b[13],12,-40341101),i=d(i,j,c,h,b[14],17,-1502002290),h=d(h,i,j,c,b[15],22,1236535329),c=e(c,h,i,j,b[1],5,-165796510),j=e(j,c,h,i,b[6],9,-1069501632),i=e(i,j,c,h,b[11],14,643717713),h=e(h,i,j,c,b[0],20,-373897302),c=e(c,h,i,j,b[5],5,-701558691),j=e(j,c,h,i,b[10],9,38016083),i=e(i,j,c,h,b[15],14,-660478335),h=e(h,i,j,c,b[4],20,-405537848),c=e(c,h,i,j,b[9],5,568446438),j=e(j,c,h,i,b[14],9,-1019803690),i=e(i,j,c,h,b[3],14,-187363961),h=e(h,i,j,c,b[8],20,1163531501),c=e(c,h,i,j,b[13],5,-1444681467),j=e(j,c,h,i,b[2],9,-51403784),i=e(i,j,c,h,b[7],14,1735328473),h=e(h,i,j,c,b[12],20,-1926607734),c=f(c,h,i,j,b[5],4,-378558),j=f(j,c,h,i,b[8],11,-2022574463),i=f(i,j,c,h,b[11],16,1839030562),h=f(h,i,j,c,b[14],23,-35309556),c=f(c,h,i,j,b[1],4,-1530992060),j=f(j,c,h,i,b[4],11,1272893353),i=f(i,j,c,h,b[7],16,-155497632),h=f(h,i,j,c,b[10],23,-1094730640),c=f(c,h,i,j,b[13],4,681279174),j=f(j,c,h,i,b[0],11,-358537222),i=f(i,j,c,h,b[3],16,-722521979),h=f(h,i,j,c,b[6],23,76029189),c=f(c,h,i,j,b[9],4,-640364487),j=f(j,c,h,i,b[12],11,-421815835),i=f(i,j,c,h,b[15],16,530742520),h=f(h,i,j,c,b[2],23,-995338651),c=g(c,h,i,j,b[0],6,-198630844),j=g(j,c,h,i,b[7],10,1126891415),i=g(i,j,c,h,b[14],15,-1416354905),h=g(h,i,j,c,b[5],21,-57434055),c=g(c,h,i,j,b[12],6,1700485571),j=g(j,c,h,i,b[3],10,-1894986606),i=g(i,j,c,h,b[10],15,-1051523),h=g(h,i,j,c,b[1],21,-2054922799),c=g(c,h,i,j,b[8],6,1873313359),j=g(j,c,h,i,b[15],10,-30611744),i=g(i,j,c,h,b[6],15,-1560198380),h=g(h,i,j,c,b[13],21,1309151649),c=g(c,h,i,j,b[4],6,-145523070),j=g(j,c,h,i,b[11],10,-1120210379),i=g(i,j,c,h,b[2],15,718787259),h=g(h,i,j,c,b[9],21,-343485551),a[0]=m(c,a[0]),a[1]=m(h,a[1]),a[2]=m(i,a[2]),a[3]=m(j,a[3])}function c(a,b,c,d,e,f){return b=m(m(b,a),m(d,f)),m(b<<e|b>>>32-e,c)}function d(a,b,d,e,f,g,h){return c(b&d|~b&e,a,b,f,g,h)}function e(a,b,d,e,f,g,h){return c(b&e|d&~e,a,b,f,g,h)}function f(a,b,d,e,f,g,h){return c(b^d^e,a,b,f,g,h)}function g(a,b,d,e,f,g,h){return c(d^(b|~e),a,b,f,g,h)}function h(a){txt="";var c,d=a.length,e=[1732584193,-271733879,-1732584194,271733878];for(c=64;c<=a.length;c+=64)b(e,i(a.substring(c-64,c)));a=a.substring(c-64);var f=[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];for(c=0;c<a.length;c++)f[c>>2]|=a.charCodeAt(c)<<(c%4<<3);if(f[c>>2]|=128<<(c%4<<3),c>55)for(b(e,f),c=0;16>c;c++)f[c]=0;return f[14]=8*d,b(e,f),e}function i(a){var b,c=[];for(b=0;64>b;b+=4)c[b>>2]=a.charCodeAt(b)+(a.charCodeAt(b+1)<<8)+(a.charCodeAt(b+2)<<16)+(a.charCodeAt(b+3)<<24);return c}function j(a){for(var b="",c=0;4>c;c++)b+=n[a>>8*c+4&15]+n[a>>8*c&15];return b}function k(a){for(var b=0;b<a.length;b++)a[b]=j(a[b]);return a.join("")}function l(a){return k(h(a))}function m(a,b){return a+b&4294967295}function m(a,b){var c=(65535&a)+(65535&b),d=(a>>16)+(b>>16)+(c>>16);return d<<16|65535&c}var n="0123456789abcdef".split("");"5d41402abc4b2a76b9719d911017c592"!=l("hello"),a.hash=l}(a),"undefined"!=typeof window)"undefined"==typeof sessionStorage&&!function(a){function b(){function b(){k.cookie=["sessionStorage="+a.encodeURIComponent(h=f.key(128))].join(";"),i=f.encode(h,i),g=new g(d,"name",d.name)}var e,k=(d.name,d.document),l=/\bsessionStorage\b=([^;]+)(;|$)/,m=l.exec(k.cookie);if(m){h=a.decodeURIComponent(m[1]),i=f.encode(h,i),g=new g(d,"name");for(var n=g.key(),e=0,o=n.length,p={};o>e;++e)0===(m=n[e]).indexOf(i)&&(j.push(m),p[m]=g.get(m),g.del(m));if(g=new g.constructor(d,"name",d.name),0<(this.length=j.length)){for(e=0,o=j.length,c=g.c,m=[];o>e;++e)m[e]=c.concat(g._c,g.escape(n=j[e]),c,c,(n=g.escape(p[n])).length,c,n);d.name+=m.join("")}}else b(),l.exec(k.cookie)||(j=null)}var d=a;try{for(;d!==d.top;)d=d.top}catch(e){}var f=function(a,b){return{decode:function(a,b){return this.encode(a,b)},encode:function(b,c){for(var d,e=b.length,f=c.length,g=[],h=[],i=0,j=0,k=0,l=0;256>i;++i)h[i]=i;for(i=0;256>i;++i)j=(j+(d=h[i])+b.charCodeAt(i%e))%256,h[i]=h[j],h[j]=d;for(j=0;f>k;++k)i=k%256,j=(j+(d=h[i]))%256,e=h[i]=h[j],h[j]=d,g[l++]=a(c.charCodeAt(k)^h[(e+d)%256]);return g.join("")},key:function(c){for(var d=0,e=[];c>d;++d)e[d]=a(1+(255*b()<<0));return e.join("")}}}(a.String.fromCharCode,a.Math.random),g=function(a){function b(a,b,c){this._i=(this._data=c||"").length,(this._key=b)?this._storage=a:(this._storage={_key:a||""},this._key="_key")}function c(a,b){var c=this.c;return c.concat(this._c,this.escape(a),c,c,(b=this.escape(b)).length,c,b)}return b.prototype.c=String.fromCharCode(1),b.prototype._c=".",b.prototype.clear=function(){this._storage[this._key]=this._data},b.prototype.del=function(a){var b=this.get(a);null!==b&&(this._storage[this._key]=this._storage[this._key].replace(c.call(this,a,b),""))},b.prototype.escape=a.escape,b.prototype.get=function(a){var b=this._storage[this._key],c=this.c,d=b.indexOf(a=c.concat(this._c,this.escape(a),c,c),this._i),e=null;return d>-1&&(d=b.indexOf(c,d+a.length-1)+1,e=b.substring(d,d=b.indexOf(c,d)),e=this.unescape(b.substr(++d,e))),e},b.prototype.key=function(){for(var a=this._storage[this._key],b=this.c,c=b+this._c,d=this._i,e=[],f=0,g=0;-1<(d=a.indexOf(c,d));)e[g++]=this.unescape(a.substring(d+=2,f=a.indexOf(b,d))),d=a.indexOf(b,f)+2,f=a.indexOf(b,d),d=1+f+1*a.substring(d,f);return e},b.prototype.set=function(a,b){this.del(a),this._storage[this._key]+=c.call(this,a,b)},b.prototype.unescape=a.unescape,b}(a);"[object Opera]"===Object.prototype.toString.call(a.opera)&&(history.navigationMode="compatible",g.prototype.escape=a.encodeURIComponent,g.prototype.unescape=a.decodeURIComponent),b.prototype={length:0,key:function(a){if("number"!=typeof a||0>a||j.length<=a)throw"Invalid argument";return j[a]},getItem:function(a){if(a=i+a,l.call(k,a))return k[a];var b=g.get(a);return null!==b&&(b=k[a]=f.decode(h,b)),b},setItem:function(a,b){this.removeItem(a),a=i+a,g.set(a,f.encode(h,k[a]=""+b)),this.length=j.push(a)},removeItem:function(a){var b=g.get(a=i+a);null!==b&&(delete k[a],g.del(a),this.length=j.remove(a))},clear:function(){g.clear(),k={},j.length=0}};var h,i=d.document.domain,j=[],k={},l=k.hasOwnProperty;j.remove=function(a){var b=this.indexOf(a);return b>-1&&this.splice(b,1),this.length},j.indexOf||(j.indexOf=function(a){for(var b=0,c=this.length;c>b;++b)if(this[b]===a)return b;return-1}),d.sessionStorage&&(b=function(){},b.prototype=d.sessionStorage),b=new b,null!==j&&(a.sessionStorage=b)}(window);else{var b={};localStorage={setItem:function(a,c){b[a]=c},getItem:function(a){return b[a]},removeItem:function(a){delete b[a]}}}if("undefined"==typeof d){var d=function(a){return this instanceof d?(a=a||{},this.options=a,this.trackerInstance=a.tracker,void this.initialize()):new d(config)};!function(b){b.prototype.options=function(){return this.options};var c=function(){var a={init:function(){this.browser=this.searchString(this.dataBrowser)||"An unknown browser",this.version=this.searchVersion(navigator.userAgent)||this.searchVersion(navigator.appVersion)||"an unknown version",this.OS=this.searchString(this.dataOS)||"an unknown OS"},searchString:function(a){for(var b=0;b<a.length;b++){var c=a[b].string,d=a[b].prop;if(this.versionSearchString=a[b].versionSearch||a[b].identity,c){if(-1!=c.indexOf(a[b].subString))return a[b].identity}else if(d)return a[b].identity}},searchVersion:function(a){var b=a.indexOf(this.versionSearchString);if(-1!=b)return parseFloat(a.substring(b+this.versionSearchString.length+1))},dataBrowser:[{string:navigator.userAgent,subString:"Chrome",identity:"Chrome"},{string:navigator.userAgent,subString:"OmniWeb",versionSearch:"OmniWeb/",identity:"OmniWeb"},{string:navigator.vendor,subString:"Apple",identity:"Safari",versionSearch:"Version"},{prop:window.opera,identity:"Opera",versionSearch:"Version"},{string:navigator.vendor,subString:"iCab",identity:"iCab"},{string:navigator.vendor,subString:"KDE",identity:"Konqueror"},{string:navigator.userAgent,subString:"Firefox",identity:"Firefox"},{string:navigator.vendor,subString:"Camino",identity:"Camino"},{string:navigator.userAgent,subString:"Netscape",identity:"Netscape"},{string:navigator.userAgent,subString:"MSIE",identity:"Explorer",versionSearch:"MSIE"},{string:navigator.userAgent,subString:"Gecko",identity:"Mozilla",versionSearch:"rv"},{string:navigator.userAgent,subString:"Mozilla",identity:"Netscape",versionSearch:"Mozilla"}],dataOS:[{string:navigator.platform,subString:"Win",identity:"Windows"},{string:navigator.platform,subString:"Mac",identity:"Mac"},{string:navigator.userAgent,subString:"iPod",identity:"iPod"},{string:navigator.userAgent,subString:"iPad",identity:"iPad"},{string:navigator.userAgent,subString:"iPhone",identity:"iPhone"},{string:navigator.platform,subString:"Linux",identity:"Linux"}]};return a.init(),a}(),d={};d.geoip=function(a,b){"undefined"!=typeof geoip2&&geoip2.city(function(b){a({latitude:a.location.latitude,longitude:a.location.longitude})},b,{timeout:2e3,w3c_geolocation_disabled:!0})};var e={};e.copyFields=function(a,b){var c=function(a,b){return function(){return b.apply(a,arguments)}};b=b||{};var d,e;for(d in a)/layerX|Y/.test(d)||(e=a[d],"function"==typeof e?b[d]=c(a,e):b[d]=e);return b},e.merge=function(a,b){var c,d,f;if(void 0===a)return a;if(void 0===b)return a;if(a instanceof Array&&b instanceof Array){for(c=[],f=0;f<a.length;f++)c.push(a[f]);for(f=0;f<b.length;f++)c.length>f?c[f]=e.merge(c[f],b[f]):c.push(b[f]);return c}if(a instanceof Object&&b instanceof Object){c={};for(d in a)c[d]=a[d];for(d in b)void 0!==c[d]?c[d]=e.merge(c[d],b[d]):c[d]=b[d];return c}return b},e.toObject=function(a){var b,c={};for(b in a)c[b]=a[b];return c},e.genGuid=function(){var a=function(){return Math.floor(65536*(1+Math.random())).toString(16).substring(1)};return a()+a()+"-"+a()+"-"+a()+"-"+a()+"-"+a()+a()+a()},e.parseQueryString=function(a){var b={};if(a.length>0){var c="?"===a.charAt(0)?a.substring(1):a;if(c.length>0)for(var d=c.split("&"),e=0;e<d.length;e++)if(d[e].length>0){var f=d[e].split("=");try{var g=decodeURIComponent(f[0]),h=f.length>1?decodeURIComponent(f[1]):"true";b[g]=h}catch(i){}}}return b},e.unparseQueryString=function(a){var b,c,d=[];for(b in a)(!a.hasOwnProperty||a.hasOwnProperty(b))&&(c=a[b],d.push(encodeURIComponent(b)+"="+encodeURIComponent(c)));var e=d.join("&");return e.length>0?"?"+e:""},e.size=function(a){if(void 0===a)return 0;if(a instanceof Array)return a.length;if(a instanceof Object){var b=0;for(var c in a)(!a.hasOwnProperty||a.hasOwnProperty(c))&&++b;return b}return 1},e.mapJson=function(a,b){var c,d;if(a instanceof Array){c=[];for(var f=0;f<a.length;f++)d=e.mapJson(a[f],b),e.size(d)>0&&c.push(d);return c}if(a instanceof Object){c={};for(var g in a)d=e.mapJson(a[g],b),e.size(d)>0&&(c[g]=d);return c}return b(a)},e.jsonify=function(a){return e.mapJson(a,function(a){if(""===a)return void 0;var b;try{b=JSON.parse(a)}catch(c){b=a}return b})},e.undup=function(a,b){b=b||250;var c=0;return function(){var d=(new Date).getTime(),e=d-c;return e>b?(c=d,a.apply(this,arguments)):void 0}},e.parseUrl=function(a){var b=document.createElement("a");return b.href=a,""===b.host&&(b.href=b.href),{hash:b.hash,host:b.host,hostname:b.hostname,pathname:b.pathname,protocol:b.protocol,query:e.parseQueryString(b.search)}},e.unparseUrl=function(a){return(a.protocol||"")+"//"+(a.host||"")+(a.pathname||"")+e.unparseQueryString(a.query)+(a.hash||"")},e.equals=function(a,b){var c=function(a,b){for(var c in a)if((!a.hasOwnProperty||a.hasOwnProperty(c))&&!e.equals(a[c],b[c]))return!1;return!0};if(a instanceof Array){if(b instanceof Array){if(a.length!==b.length)return!1;for(var d=0;d<a.length;d++)if(!e.equals(a[d],b[d]))return!1;return!0}return!1}return a instanceof Object?b instanceof Object?c(a,b)&&c(b,a):!1:a===b},e.isSamePage=function(a,b){return a=a instanceof String?e.parseUrl(a):a,b=b instanceof String?e.parseUrl(b):b,a.protocol===b.protocol&&a.host===b.host&&a.pathname===b.pathname&&e.equals(a.query,b.query)},e.qualifyUrl=function(a){var b=function(a){return a.split("&").join("&amp;").split("<").join("&lt;").split('"').join("&quot;")},c=document.createElement("div");return c.innerHTML='<a href="'+b(a)+'">x</a>',c.firstChild.href},e.padLeft=function(a,b,c){var d="undefined"!=typeof c?c:"0",e=new Array(1+b).join(d);return(e+a).slice(-e.length)};var f={};f.getFormData=function(a){for(var b={},c=function(a,c){""===a&&(a="anonymous");var d=b[a];null!=d?d instanceof Array?b[a].push(c):b[a]=[d,c]:b[a]=c},d=0;d<a.elements.length;d++){var e=a.elements[d],f=e.tagName.toLowerCase();if("input"==f||"textfield"==f)"off"!==(e.getAttribute("autocomplete")||"").toLowerCase()&&"password"!==e.type&&("radio"!==e.type||e.checked)&&c(e.name,e.value);else if("select"==f){var g=e.options[e.selectedIndex];c(e.name,g.value)}}return b},f.monitorElements=function(a,b,c){c=c||50;var d=function(){for(var e=document.getElementsByTagName(a),f=0;f<e.length;f++){var g=e[f],h=g.getAttribute("scribe_scanned");if(!h){g.setAttribute("scribe_scanned",!0);try{b(g)}catch(i){window.onerror(i)}}}setTimeout(d,c)};setTimeout(d,0)},f.getDataset=function(a){if("undefined"!=typeof a.dataset)return e.toObject(a.dataset);if(a.attributes){for(var b={},c=a.attributes,d=0;d<c.length;d++){var f=c[d].name,g=c[d].value;0===f.indexOf("data-")&&(f=f.substr("data-".length),b[f]=g)}return b}return{}},f.genCssSelector=function(a){for(var b="";a!=document.body;){var c=a.id,d="string"==typeof a.className?a.className.trim().split(/\s+/).join("."):"",e=a.nodeName.toLowerCase();c&&""!==c&&(c="#"+c),""!==d&&(d="."+d);for(var f=e+c+d,g=a.parentNode,h=1,i=0;i<g.childNodes.length&&g.childNodes[i]!==a;i++){var j=g.childNodes[i].tagName;void 0!==j&&(h+=1)}""!==b&&(b=">"+b),b=f+":nth-child("+h+")"+b,a=g}return b},f.getNodeDescriptor=function(a){return{id:a.id,selector:f.genCssSelector(a),title:""===a.title?void 0:a.title,data:f.getDataset(a)}},f.getAncestors=function(a){for(var b=a,c=[];b&&b!==document.body;)c.push(b),b=b.parentNode;return c},f.simulateMouseEvent=function(a,b,c){var d={HTMLEvents:/^(?:load|unload|abort|error|select|change|submit|reset|focus|blur|resize|scroll)$/,MouseEvents:/^(?:click|dblclick|mouse(?:down|up|over|move|out))$/};c=e.merge({pointerX:0,pointerY:0,button:0,ctrlKey:!1,altKey:!1,shiftKey:!1,metaKey:!1,bubbles:!0,cancelable:!0},c||{});var f,g=null;for(var h in d)if(d[h].test(b)){g=h;break}if(!g)throw new SyntaxError("Only HTMLEvents and MouseEvents interfaces are supported");if(document.createEvent)f=document.createEvent(g),"HTMLEvents"===g?f.initEvent(b,c.bubbles,c.cancelable):f.initMouseEvent(b,c.bubbles,c.cancelable,document.defaultView,c.button,c.pointerX,c.pointerY,c.pointerX,c.pointerY,c.ctrlKey,c.altKey,c.shiftKey,c.metaKey,c.button,a),a.dispatchEvent(f);else{c.clientX=c.pointerX,c.clientY=c.pointerY;var i=document.createEventObject();f=e.merge(i,c);try{a.fireEvent("on"+b,f)}catch(j){a.fireEvent("on"+b)}}return a};var g={};g.removeElement=function(a,b,c){var d=a.slice((c||b)+1||a.length);return a.length=0>b?a.length+b:b,a.push.apply(a,d)},g.toArray=function(a){var b,c=[],d=a.length;for(c.length=a.length,b=0;d>b;b++)c[b]=a[b];return c},g.contains=function(a,b){return g.exists(a,function(a){return a===b})},g.diff=function(a,b){var c,d,e=[];for(c=0;c<a.length;c++)d=a[c],g.contains(b,d)||e.push(d);return e},g.exists=function(a,b){for(var c=0;c<a.length;c++)if(b(a[c]))return!0;return!1},g.map=function(a,b){var c,d=[];for(c=0;c<a.length;c++)d.push(b(a[c]));return d};var h={};h.getFingerprint=function(){var b=[JSON.stringify(h.getPluginsData()),JSON.stringify(h.getLocaleData()),navigator.userAgent.toString()];return a.hash(b.join(""))},h.getBrowserData=function(){h.getFingerprint();return{ua:navigator.userAgent,name:c.browser,version:c.version,platform:c.OS,language:navigator.language||navigator.userLanguage||navigator.systemLanguage,plugins:h.getPluginsData()}},h.getUrlData=function(){var a=document.location;return{hash:a.hash,host:a.host,hostname:a.hostname,pathname:a.pathname,protocol:a.protocol,query:e.parseQueryString(a.search)}},h.getDocumentData=function(){return{title:document.title,referrer:document.referrer&&e.parseUrl(document.referrer)||void 0,url:h.getUrlData()}},h.getScreenData=function(){return{height:screen.height,width:screen.width,colorDepth:screen.colorDepth}},h.getLocaleData=function(){var a,b,c=new RegExp("([A-Z]+-[0-9]+) \\(([A-Z]+)\\)").exec((new Date).toString());return c&&c.length>=3&&(a=c[1],b=c[2]),{language:navigator.systemLanguage||navigator.userLanguage||navigator.language,timezoneOffset:(new Date).getTimezoneOffset(),gmtOffset:a,timezone:b}},h.getPageloadData=function(){document.location;return{browser:h.getBrowserData(),document:h.getDocumentData(),screen:h.getScreenData(),locale:h.getLocaleData()}},h.getPluginsData=function(){for(var a=[],b=navigator.plugins,c=0;c<b.length;c++){var d=b[c];a.push({name:d.name,description:d.description,filename:d.filename,version:d.version,mimeType:d.length>0?{type:d[0].type,description:d[0].description,suffixes:d[0].suffixes}:void 0})}return a};var i=function(){this.handlers=[],this.onerror=console&&console.log||window.onerror||function(a){}};i.prototype.push=function(a){this.handlers.push(a)},i.prototype.dispatch=function(){var a,b=Array.prototype.slice.call(arguments,0);for(a=0;a<this.handlers.length;a++)try{this.handlers[a].apply(null,b)}catch(c){onerror(c)}};var j={};return j.onready=function(a){null!=document.body?a():setTimeout(function(){j.onready(a)},10)},j.onevent=function(a,b,c,d){var f=function(a){return function(b){b||(b=window.event),b=e.copyFields(b),b.target=b.target||b.srcElement,b.keyCode=b.keyCode||b.which||b.charCode,b.which=b.which||b.keyCode,b.charCode="number"==typeof b.which?b.which:b.keyCode,b.timeStamp=b.timeStamp||(new Date).getTime(),b.target&&3==b.target.nodeType&&(b.target=b.target.parentNode);var c;return b.preventDefault||(b.preventDefault=function(){c=!1}),a(b)||c}},g=f(d);a.addEventListener?a.addEventListener(b,g,c):a.attachEvent&&a.attachEvent("on"+b,g)},j.onexit=function(){var a=!1,b=new i,c=function(c){a||(b.dispatch(c),a=!0)};j.onevent(window,"unload",void 0,c);var d=function(a){var b=a.onunload||function(a){};a.onunload=function(a){c(),b(a)}};return d(window),j.onready(function(){d(document.body)}),function(a){b.push(a)}}(),j.onengage=function(){var a=new i,b=[];return j.onready(function(){j.onevent(document.body,"mouseover",!0,function(a){b.push(a)}),j.onevent(document.body,"mouseout",!0,function(c){var d,e;for(d=b.length-1;d>=0;d--)if(b[d].target===c.target){e=b[d],g.removeElement(b,d);break}if(void 0!==e){var f=c.timeStamp-e.timeStamp;f>=1e3&&2e4>=f&&a.dispatch(e,c)}})}),function(b){a.push(b)}}(),j.onhashchange=function(){var a=new i,b=document.location.hash,c=function(c){var d=document.location.hash;b!=d&&(b=d,c.hash=d,a.dispatch(c))};return window.onhashchange?j.onevent(window,"hashchange",!1,c):setInterval(function(){c({})},25),function(b){a.push(b)}}(),j.onerror=function(){var a=new i;return"function"==typeof window.onerror&&a.push(window.onerror),window.onerror=function(b,c,d){a.dispatch(b,c,d)},function(b){a.push(b)}}(),j.onsubmit=function(){var a=new i,b=e.undup(function(b){a.dispatch(b)});return j.onready(function(){j.onevent(document.body,"submit",!0,function(a){b(a)}),j.onevent(document.body,"keypress",!1,function(a){if(13==a.keyCode){var c=a.target,d=c.form;d&&(a.form=d,b(a))}}),j.onevent(document.body,"click",!1,function(a){var c=a.target,d=(c.type||"").toLowerCase();!c.form||"submit"!==d&&"button"!==d||(a.form=c.form,b(a))})}),function(b){a.push(b)}}(),b.prototype.initialize=function(){var a=this;this.options=e.merge({bucket:"none",breakoutUsers:!1,breakoutVisitors:!1,waitOnTracker:!1,resolveGeo:!1,trackPageViews:!1,trackClicks:!1,trackHashChanges:!1,trackEngagement:!1,trackLinkClicks:!1,trackRedirects:!1,trackSubmissions:!1},this.options),this.javascriptRedirect=!0,this.context={},this.context.fingerprint=h.getFingerprint(),this.context.sessionId=function(){var a=sessionStorage.getItem("scribe_sid")||e.genGuid();return sessionStorage.setItem("scribe_sid",a),a}(),this.context.visitorId=function(){var a=localStorage.getItem("scribe_vid")||e.genGuid();return localStorage.setItem("scribe_vid",a),a}(),this.context.userId=JSON.parse(localStorage.getItem("scribe_uid")||"null"),this.context.userProfile=JSON.parse(localStorage.getItem("scribe_uprofile")||"null"),a.oldHash=document.location.hash;var b=function(b){if(a.oldHash!==b){var c=b.substring(1),d=document.getElementById(c),g=e.merge({url:e.parseUrl(document.location)},d?f.getNodeDescriptor(d):{id:c});a.track("jump",{target:g,source:{url:e.merge(e.parseUrl(document.location),{hash:a.oldHash})}}),a.oldHash=b}};if(this.options.resolveGeo&&d.geoip(function(b){a.context.geo=b}),this.options.trackPageView&&j.onready(function(){a.pageview()}),this.options.trackClicks&&j.onready(function(){j.onevent(document.body,"click",!0,function(b){var c=f.getAncestors(b.target);g.exists(c,function(a){return"A"===a.tagName})||a.track("click",{target:f.getNodeDescriptor(b.target)})})}),this.options.trackHashChanges&&j.onhashchange(function(a){b(a.hash)}),this.options.trackEngagement&&j.onengage(function(b,c){a.track("engage",{target:f.getNodeDescriptor(b.target),duration:c.timeStamp-b.timeStamp})}),this.options.trackLinkClicks){var c=this;f.monitorElements("a",function(d){j.onevent(d,"click",!0,function(g){if(g.isTrusted){var h=g.target;a.javascriptRedirect=!1,setTimeout(function(){a.javascriptRedirect=!0},500);var i=e.parseUrl(d.href),j={target:e.merge({url:i},f.getNodeDescriptor(h))};e.isSamePage(i,document.location.href)?(a.oldHash=void 0,b(document.location.hash)):i.hostname===document.location.hostname?a.trackLater("click",j):(c.options.waitOnTracker&&g.preventDefault(),a.track("click",j,function(){a.javascriptRedirect=!1,c.options.waitOnTracker&&f.simulateMouseEvent(h,"click")}))}})})}this.options.trackRedirects&&j.onexit(function(b){a.javascriptRedirect&&a.trackLater("redirect")}),this.options.trackSubmissions&&j.onsubmit(function(b){b.form&&(b.form.formId||(b.form.formId=e.genGuid()),a.trackLater("formsubmit",{form:e.merge({formId:b.form.formId},f.getFormData(b.form))}))}),this._loadOutbox(),this._sendOutbox()},b.prototype.getPath=function(a){var b,c=new Date,d=this.context.userId?this.options.breakoutUsers?"/users/"+this.context.userId+"/":"/users/":this.options.breakoutVisitors?"/visitors/"+this.context.visitorId+"/":"/visitors/";b=/daily|day/.test(this.options.bucket)?c.getUTCFullYear()+"-"+e.padLeft(c.getUTCMonth(),2)+"-"+e.padLeft(c.getUTCDate(),2)+"/":/month/.test(this.options.bucket)?c.getUTCFullYear()+"-"+e.padLeft(c.getUTCMonth(),2)+"/":/year/.test(this.options.bucket)?c.getUTCFullYear()+"/":"";var f=a+"/";return d+b+f},b.prototype._saveOutbox=function(){localStorage.setItem("scribe_outbox",JSON.stringify(this.outbox))},b.prototype._loadOutbox=function(){this.outbox=JSON.parse(localStorage.getItem("scribe_outbox")||"[]")},b.prototype._sendOutbox=function(){for(var a=0;a<this.outbox.length;a++){var b=this.outbox[a],c=b.value.event;if(g.contains(["redirect","formSubmit"],c)&&(b.value.target=e.jsonify(e.merge(b.value.target||{},{url:e.parseUrl(document.location)}))),"redirect"===c)try{var d=e.unparseUrl(b.value.source.url),f=e.unparseUrl(b.value.target.url);d===f&&(b.value.event="reload")}catch(h){window.onerror&&window.onerror(h)}try{this.trackerInstance.tracker(b)}catch(h){window.onerror&&window.onerror(h)}}this.outbox=[],this._saveOutbox()},b.prototype.identify=function(a,b,c,d,f){this.context.userId=a,this.context.userProfile=b,localStorage.setItem("scribe_uid",JSON.stringify(a)),localStorage.setItem("scribe_uprofile",JSON.stringify(b||{})),this.context=e.merge(c||{},this.context),this.trackerInstance.tracker({path:this.getPath("profile"),value:this._createEvent(void 0,b),op:"replace",success:d,failure:f})},b.prototype._createEvent=function(a,b){return b=b||{},b.timestamp=b.timestamp||(new Date).toISOString(),b.event=a,b.source=e.merge({url:e.parseUrl(document.location)},b.source||{}),e.jsonify(e.merge(this.context,b))},b.prototype.track=function(a,b,c,d){this.trackerInstance.tracker({path:this.getPath("events"),value:this._createEvent(a,b),op:"append",success:c,failure:d})},b.prototype.trackLater=function(a,b){this.outbox.push({path:this.getPath("events"),value:this._createEvent(a,b),op:"append"}),this._saveOutbox()},b.prototype.group=function(a,b,c,d){this.context.userGroupId=a,this.context.userGroupProfile=b,this.context=e.merge(context||{},this.context),this.trackerInstance.tracker({path:this.getPath("groups"),value:this._createEvent(void 0,b),op:"replace",success:c,failure:d})},b.prototype.pageview=function(a,b,c){a=a||document.location,this.track("pageview",e.merge(h.getPageloadData(),{url:e.parseUrl(a+"")}),b,c)},b}(d)}return d});

/***/ }),
/* 1 */
/***/ (function(module, exports) {

/*global module */
/*jshint esversion: 6 */

var dlgr = window.dlgr = (window.dlgr || {});

var ScribeDallingerTracker = function(config) {
  if (!(this instanceof ScribeDallingerTracker)) return new ScribeDallingerTracker(config);

  this.config = config;
  this.init();
};

ScribeDallingerTracker.prototype.tracker = function(info) {
  var config = this.config;
  var path = info.path;
  var value = this.stripPII(info.value || {});
  var data = new FormData();

  // Only track events
  if (path.indexOf('/events/') < 0) {
    return;
  }
  if (config.base_url) {
    data.append('info_type', 'TrackingEvent');
    data.append('details', JSON.stringify(value));

    var xhr = new XMLHttpRequest();
    if (info.success) xhr.addEventListener("load", info.success);
    if (info.failure) {
      xhr.addEventListener("error", info.failure);
      xhr.addEventListener("abort", info.failure);
    }
    xhr.open('POST', config.base_url.replace(/\/$/, "") + '/info/' + dlgr.node_id, true);
    xhr.send(data);
  } else if (info.failure) {
    setTimeout(info.failure, 0);
  }
};

ScribeDallingerTracker.prototype.stripPII = function(value) {
  // Remove possible PII
  delete value.fingerprint;
  delete value.visitorId;
  try {
    delete value.source.url.query.worker_id;
    delete value.source.url.query.workerId;
  } catch (e) {
    // Doesn't matter
  }
  try {
    delete value.target.url.query.worker_id;
    delete value.target.url.query.workerId;
  } catch (e) {
    // Doesn't matter
  }
  return value;
};

ScribeDallingerTracker.prototype.init = function() {
  var config = this.config;
  var getNodeDescriptor = function(node) {
    return {
      id:         node.id,
      selector:   'document',
      title:      node.title === '' ? undefined : node.title,
      data:       {}
    };
  };

  var trackSelectedText = function (e) {
    var text = '';
    if (window.getSelection) {
      text = window.getSelection();
    } else if (document.getSelection) {
      text = document.getSelection();
    } else if (document.selection) {
      text = document.selection.createRange().text;
    }
    text = text.toString();
    if (dlgr.tracker && text) {
      dlgr.tracker.track('text_selected', {
        target: getNodeDescriptor(e.target),
        selected: text
      });
    }
  };

  var trackScroll = function () {
    var doc = document.documentElement, body = document.body;
    var left = (doc && doc.scrollLeft || body && body.scrollLeft || 0);
    var top = (doc && doc.scrollTop  || body && body.scrollTop  || 0);
    dlgr.tracker.track('scroll', {
      target: getNodeDescriptor(doc || body),
      top: top,
      bottom: top + window.innerHeight,
      left: left,
      right: left + window.window.innerWidth
    });
  };

  var scrollHandler = function () {
    if (!dlgr.tracker) {
      return;
    }
    if (dlgr.scroll_timeout) {
      clearTimeout(dlgr.scroll_timeout);
    }
    dlgr.scroll_timeout = setTimeout(trackScroll, 500);
  };

  var trackContents = function () {
    if (!dlgr.tracker) {
      return;
    }
    var doc = document.documentElement || document.body;
    var content = doc.innerHTML;
    dlgr.tracker.track('page_contents', {
      target: getNodeDescriptor(doc),
      content: content
    });
  };

  if (config.trackSelection) {
    if (document.addEventListener) {
      document.addEventListener('mouseup', trackSelectedText);
    } else if (window.attachEvent)  {
      document.attachEvent('onmouseup', trackSelectedText);
    }
  }
  if (config.trackScroll) {
    if (window.addEventListener) {
      window.addEventListener('scroll', scrollHandler);
    } else if (window.attachEvent)  {
      window.attachEvent('onscroll', scrollHandler);
    }
  }
  if (config.trackContents) {
    setTimeout(trackContents, 100);
  }
};

module.exports.ScribeDallingerTracker = ScribeDallingerTracker;


/***/ }),
/* 2 */
/***/ (function(module, exports, __webpack_require__) {

var require;/*global require */
/*jshint esversion: 6 */

var dlgr = window.dlgr = (window.dlgr || {});

(function (require) {

  var Scribe = __webpack_require__(0);
  var ScribeDallinger = __webpack_require__(1);

  function getParticipantId() {
    var participant_id = dlgr.participant_id;
    return participant_id === true ? null : participant_id;
  }

  function getNodeId() {
    return dlgr.node_id;
  }

  function getBaseUrl() {
    if (dlgr.experiment_url) return dlgr.experiment_url;
    return '/';
  }

  function configuredTracker() {
    return new ScribeDallinger.ScribeDallingerTracker({
      participant_id: getParticipantId(),
      node_id: getNodeId(),
      base_url: getBaseUrl(),
      trackScroll: true,
      trackSelection: true,
      trackContents: true
    });
  }

  if (!dlgr.tracker) {
    dlgr.tracker = new Scribe({
      tracker:    configuredTracker(),
      trackPageViews:   true,
      trackClicks:      true,
      trackHashChanges: true,
      trackEngagement:  true,
      trackLinkClicks:  true,
      trackRedirects:   true,
      trackSubmissions: true
    });
  }

}(require));


/***/ })
/******/ ]);
//# sourceMappingURL=tracker.js.map