/*
 * The MIT License (MIT)
 * 
 * Copyright (c) 2014 Jonathan Giroux (Bloutiouf)
 * 
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 * 
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 * 
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

var async = require('async'),
	crypto = require('crypto'),
	execFile = require('child_process').execFile,
	fs = require('fs'),
	merge = require('merge'),
	path = require('path'),
	request = require('request'),
	rimraf = require('rimraf');

var defaultOptions = {
	hash: 'sha256'
};

function bareName(file) {
	return path.basename(file, path.extname(file));
}

try {
	addons = JSON.parse(fs.readFileSync('addons.json'));
} catch (err) {
	addons = {};
}

exports.addons = addons;

function saveAddons(callback) {
	return fs.writeFile('addons.json', JSON.stringify(addons, null, '\t'), callback);
}

function extractBlInfo(content, callback) {
	var match = /bl_info\s*=\s*\{[^]*?\}/.exec(content.toString());
	if (!match) {
		return callback(new Error('bl_info missing.'));
	}
	
	var python = execFile('python', function(err, stdout, stderr) {
		if (err) {
			return callback(err);
		}
		return callback(null, JSON.parse(stdout));
	});
	
	python.stdin.write(match[0]);
	python.stdin.write('\nimport json\nprint(json.dumps(bl_info, separators=(",", ":")))');
	return python.stdin.end();
}

exports.add = function(url, options, callback) {
	if (!callback) {
		callback = options;
		options = {};
	}
	options = merge(defaultOptions, options);
	
	if (!url) {
		return callback('Please give an url');
	}
	
	var hashAlgorithm = options.hash || 'sha256';
	if (crypto.getHashes().indexOf(hashAlgorithm) === -1) {
		throw hashAlgorithm + ' is not supported';
	}
	
	function handleScript(name, content) {
		var h = crypto.createHash(hashAlgorithm);
		h.update(content);
		var hash = h.digest('hex');
		
		function addToAddons(name, content, file, peers, callback) {
			return extractBlInfo(content, function(err, info) {
				if (err) {
					return callback(err);
				}
				
				var fields = ['name', 'description', 'author', 'version', 'blender', 'location', 'category'];
				for (var i = 0, n = fields.length; i < n; ++i) {
					var field = fields[i];
					if (!info.hasOwnProperty(field)) {
						return callback(new Error('Missing field: ' + field + '.'));
					}
				}
				
				var addon = {
					info: info,
					url: url
				};
				
				addon[hashAlgorithm] = hash;
				
				if (peers.length) {
					addon.peers = peers;
				}
				
				if (file) {
					addon.file = file;
				}
				
				addons[name] = addon;
				
				if (!options.simulate) {
					return saveAddons(addons, function(err) {
						return callback(err, addon);
					});
				} else {
					return callback(null, addon);
				}
			});
		}
		
		return addToAddons(name, content, true, [], function(err, addon) {
			if (err) {
				return async.waterfall([
					function(callback) {
						return rimraf('tmp', callback);
					},
					function(callback) {
						return fs.mkdir('tmp', callback);
					},
					function(callback) {
						return fs.writeFile('tmp/download', content, callback);
					},
					function(callback) {
						return execFile('7z', ['x', '-otmp/archive', 'tmp/download'], callback);
					},
					function(stdout, stderr, callback) {
						var archiveDir = 'tmp/archive';
						return fs.readdir(archiveDir, function(err, files) {
							if (err) {
								return callback(err);
							}
							
							return async.map(files, function(file, callback) {
								var ext = path.extname(file);
								if (file === '__MACOSX' || ext !== '' || ext !== '.py') {
									return callback();
								}
								
								var archiveFile = path.join(archiveDir, file);
								return fs.stat(archiveFile, function(err, stats) {
									if (err) {
										return callback(err);
									}
									
									if (stats.isFile()) {
										return fs.readFile(archiveFile, function(err, content) {
											return callback(err, [bareName(file), content, false]);
										});
									}
									
									if (stats.isDirectory()) {
										return fs.readFile(path.join(archiveFile, '__init__.py'), function(err, content) {
											return callback(err, [file, content, false]);
										});
									}
									
									return callback();
								});
							}, callback);
						});
					},
					function(descs, callback) {
						descs = descs.filter(function(desc) {
							return !!desc;
						});
						
						return async.map(descs, function(desc, callback) {
							desc.push(descs.filter(function(d) {
								return d !== desc;
							}).map(function(d) {
								return d[0];
							}));
							desc.push(callback);
							return addToAddons.apply(this, desc);
						}, callback);
					},
					function(addons, callback) {
						return rimraf('tmp', function(err) {
							return callback(err, addons);
						});
					}
				], callback);
			} else {
				return callback(null, addon);
			}
		});
	}
	
	if (url.indexOf('://') !== -1) {
		return request({
			url: url,
			encoding: null
		}, function(err, response, body) {
			if (err) {
				return callback(err);
			}
			
			if (response.statusCode !== 200) {
				return callback(new Error(response.statusCode + ': ' + body));
			}
			
			return handleScript(bareName(url.split('/').pop()), body);
		});
	} else {
		return fs.readFile(url, function(err, content) {
			if (err) return callback(err);
			return handleScript(path.basename(url, path.extname(url)), content);
		});
	}
};

exports.list = function(options, callback) {
	if (!callback) {
		callback = options;
		options = {};
	}
	options = merge(defaultOptions, options);
	
	var list = [];
	for (var name in addons) {
		var info = addons[name].info;
		list.push(name + ': ' + info.version.join('.'));
	}
	list.sort().forEach(function(item) {
		return console.log(item);
	});
	return callback();
};

exports.remove = function(name, options, callback) {
	if (!callback) {
		callback = options;
		options = {};
	}
	options = merge(defaultOptions, options);
	
	if (!addons.hasOwnProperty(name)) {
		return callback(name + " is not in the registry");
	}
	
	delete addons[name];
	
	if (!options.simulate) {
		return saveAddons(callback);
	} else {
		return callback();
	}
};

if (require.main === module) {
	ycommands = require('ycommands')
		.usage('Usage: $0 command')
		.help('h')
		.options('hash', {
			default: defaultOptions.hash,
			description: 'Hash algorithm'
		})
		.option('s', {
			alias: 'simulate',
			boolean: true,
			description: 'Do not save changes to addons.json'
		})
		.command('add url|path ...', 'Add an addon', function(argv, callback) {
			return async.each(argv._.slice(1), function(url, callback) {
				return exports.add(url, argv, callback);
			}, callback);
		})
		.command('list', 'List addons', exports.list)
		.command('remove name ...', 'Remove an addon.', function(argv, callback) {
			return async.each(argv._.slice(1), function(name, callback) {
				return exports.remove(name, argv, callback);
			}, callback);
		})
		.execute(function(err) {
			if (err) {
				throw err;
			}
		});
}
