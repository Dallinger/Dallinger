var draw_network = function () {
    var template_globals = templateGlobals();
    var network = null;
    var net_structure = template_globals.network_structure || {}; // this  is a container for all the data coming from the route
    var vis_options = template_globals.vis_options || {}; // This is a set of overrides for the vis options

    var type_network_sort = $('#sortBy').val();
    // Always sort by id
    net_structure.networks.sort(function (first, second) {
        return second.id - first.id;
    });
    if (type_network_sort !== 'network_id') {
        var values = [];
        net_structure.networks.forEach(function (n) {
            values.push(n[type_network_sort])
        })
        var max_val = Math.max.apply(Math, values);
        net_structure.networks.sort(function (first, second) {
            return first[type_network_sort] - second[type_network_sort];
        });
    }


    var selected_networks = [];
    var hidden_network_ids = [];

    $('#order').children().each(function (index, element) {
        if ($(element).hasClass('active')) {
            if (index === 0) {
                net_structure.networks = net_structure.networks.reverse();
            }
        }
    });

    var max_networks = $('#max-networks').val();
    if (max_networks === '') {
        max_networks = null
    } else {
        max_networks = parseInt(max_networks);
    }

    var search_key = $('#search').val();
    var count_networks = 0;
    net_structure.networks.forEach(function (network) {
        var network_string = JSON.stringify(network).toLowerCase();
        var include_network = network_string.includes(search_key) && $('#val-' + network.id)[0].checked;
        if (include_network) {

            if (max_networks !== null && count_networks >= max_networks) {
                hidden_network_ids.push(network.id);
            } else {
                selected_networks.push(network);

            }
            count_networks += 1;
        } else {
            hidden_network_ids.push(network.id);
        }
    });

    // Remove all infos for
    net_structure.infos = net_structure.infos.filter(function (info) {
        return !(hidden_network_ids.includes(info['network_id']))
    })
    net_structure.nodes = net_structure.nodes.filter(function (node) {
        return !(hidden_network_ids.includes(node['network_id']))
    })

    net_structure.networks = selected_networks;

    /// set display options and groups: this will modify the way the network show up.
    function getOptions() {
        var options = {
            layout: {
                improvedLayout: false,
                hierarchical: {
                    direction: 'UD',
                    sortMethod: 'directed',
                    edgeMinimization: false, // this is super important as of a bug in the library
                    nodeSpacing: 200, // important due to a bug in the library
                    treeSpacing: 200 // important due to a bug in the librarys
                }
            },
            interaction: {
                dragNodes: false,
                hover: false,
            },
            physics: {
                enabled: false,
                stabilization: false
            },
            edges: {
                width: 2
            },

            groups: {

                failed_nodes: {
                    color: 'red'
                },

                good_nodes: {
                    font: {
                        color: '#ffffff'
                    }
                },

                failed_sources: {
                    color: {background: 'red', border: 'black'},
                    border: 5,
                    size: 30
                },

                good_sources: {
                    color: {background: 'blue', border: 'black'},
                    border: 5,
                    size: 30,
                    font: {
                        color: '#ffffff'
                    }
                },

                group_networks_open: {
                    shape: 'icon',
                    icon: {
                        face: 'FontAwesome',
                        code: '\uf0c2',
                        size: 80,
                        color: 'green'
                    },
                    font: {
                        size: 14,
                        color: 'green'
                    }
                },

                group_networks_close: {
                    shape: 'icon',
                    icon: {
                        face: 'FontAwesome',
                        code: '\uf0c2',
                        size: 80,
                        color: 'rgb(0,0,100)'
                    },
                    font: {
                        size: 14,
                        color: 'blue'
                    }
                },

                group_father: {
                    shape: 'icon',
                    icon: {
                        face: 'FontAwesome',
                        code: '\uf0c2',
                        size: 120,
                        color: 'green'
                    },
                    font: {
                        size: 25,
                        color: '#000000'
                    }
                },

                good_infos: {
                    shape: 'icon',
                    icon: {
                        face: 'FontAwesome',
                        code: '\uf0e5',
                        size: 30,
                        color: 'blue'
                    }
                },

                failed_infos: {
                    shape: 'icon',
                    icon: {
                        face: 'FontAwesome',
                        code: '\uf0e5',
                        size: 30,
                        color: 'red'
                    }
                }
            }
        };
        // Merge custom and default options
        Object.assign(options, vis_options);
        return options;
    }

    /// Draw the network
    /// This long function is drawing the network structure.
    function getnNetwork() {
        var i, j, from, to, roles, net, networks_roles, my_role, mclr,
            is_found, roles_colors, clr, rr, gg, bb, count_nodes,
            participant, participant_id, node, msg, mgroup, vector,
            info, my_node_id, tran, group_fathers, gtitle, min_id,
            to_min, father, from_node, node_viz, experiment_node;
        var nodes = []; // list of all nodes
        var edges = []; // list of all edges
        var list_of_nodes = []; // list of objects with nodes (not only nodes for example networks)
        var list_of_participants = []; // list of objects with participants
        var list_of_node_indx = []; // list of objects with nodes
        var map_infoid_to_infonum = {}; // map info id to nodes in the visualization

        /// These lines finds all the roles that involved  in this networks (typically "experiment"/"practice" but this is general)
        roles = []; // list of unique roles
        networks_roles = []; // the role of each network
        for (i = 0; i < net_structure.networks.length; i++) {
            net = net_structure.networks[i];
            my_role = net.role;

            is_found = false;
            for (j = 0; j < roles.length; j++) {
                if (my_role.localeCompare(roles[j]) == 0) {
                    is_found = true;
                    break;
                }

            }
            if (!is_found) {
                networks_roles[net.id] = roles.length;
                roles[roles.length] = my_role;

            } else {
                networks_roles[net.id] = j;
            }
        }

        roles_colors = []; ///  assign pseudorandom colors for each role
        for (j = 0; j < roles.length; j++) {
            rr = 50 + (((j + 3) * 11557) % 200); // pseudorandom colors
            gg = 50 + (((j + 3171) * 31511) % 200);
            bb = 50 + (((j + 371) * 11517) % 200);
            clr = 'rgb(' + String(rr) + ',' + String(gg) + ',' + String(bb) + ')';
            roles_colors[j] = clr;
        }

        // find all participants and make list, also asigned unique colors to participants
        for (i = 0; i < net_structure.participants.length; i++) {
            participant = net_structure.participants[i];
            participant_id = participant.id;
            if (participant_id == null) {
                participant_id = 0;
                participant = '<empty>';
            }
            rr = 10 + (((i + 357) * 2551) % 150); // pseudorandom colors
            gg = 30 + (((i + 3571) * 2511) % 200);
            bb = 100 + (((i + 3571) * 2511) % 150);
            participant.clr = 'rgb(' + String(rr) + ',' + String(gg) + ',' + String(bb) + ')';
            list_of_participants[participant_id] = participant;
        }

        // preperation to push to the graph all nodes from the data
        experiment_node = {
            id: 0,
            label: 'Experiment',
            title: 'Experiment',
            group: 'group_experiment',
            font: {align: 'inside'},
            icon: {
                face: 'FontAwesome',
                code: '\uf0c2',
                size: 120,
                color: roles_colors[0]
            }
        };
        nodes.push(experiment_node);

        count_nodes = 1;
        for (i = 0; i < net_structure.nodes.length; i++) {
            node = net_structure.nodes[i];
            count_nodes++; // count the nodes
            list_of_nodes[node.id] = node;
            list_of_node_indx[node.id] = count_nodes;

            /// find if the node is a source:
            if (node.type.toLowerCase().search('source') > 0) {
                msg = 'source:';
                if (node.failed) {
                    mgroup = 'failed_sources';
                } else {
                    mgroup = 'good_sources';
                }
            } else {
                msg = '';
                if (node.failed) {
                    mgroup = 'failed_nodes';
                } else {
                    mgroup = 'good_nodes';
                }
            }

            // find participant and show it on the graph
            participant_id = node.participant_id;
            participant = {};
            if (participant_id == null) {
                participant_id = 0;
                if (!node.failed) {
                    participant.clr = 'blue';
                }
            } else {
                participant = list_of_participants[participant_id];
            }
            if (node.failed) {
                clr = 'red';
            } else {
                clr = participant.clr;
            }

            node.object_type = 'Node';

            nodes.push({
                id: list_of_node_indx[node.id],
                label: msg + String(node.id),
                title: (node.type || '') + ':' + String(node.id),
                color: clr,
                group: mgroup,
                font: {align: 'inside'},
                data: node
            });
        }

        // create edges for vectors
        for (i = 0; i < net_structure.vectors.length; i++) {
            vector = net_structure.vectors[i];
            from = vector.origin_id;
            to = vector.destination_id;
            if (vector.failed) {
                mclr = 'red';
            } else {
                mclr = 'blue';
            }
            vector.object_type = 'Vector';
            edges.push({
                from: list_of_node_indx[from],
                to: list_of_node_indx[to],
                arrows: 'to',
                title: ('vector:' + String(vector.id) + ' (' + String(vector.origin_id) + '→' + String(vector.destination_id) + ')'),
                data: vector,
                color: mclr
            });
        }

        // now pushes infos
        for (i = 0; i < net_structure.infos.length; i++) {
            info = net_structure.infos[i];
            count_nodes++;
            map_infoid_to_infonum[info.id] = count_nodes;

            my_node_id = count_nodes;
            to = my_node_id;
            from = info.origin_id;
            from_node = list_of_nodes[from];
            node_viz = nodes[list_of_node_indx[from] - 1];
            participant_id = info.participant_id || from_node.participant_id || null;
            if (participant_id === null) {
                participant = {};
                participant_id = 0;
                participant.clr = 'black';
                participant = '<empty>';
            } else {
                participant = list_of_participants[participant_id];
            }
            if (participant_id !== 0 && node_viz.color !== 'red' && participant_id !== from_node.participant_id) {
                if (from_node.participant_id === null) {
                    node_viz.color = participant.clr;
                } else {
                    node_viz.color = 'black';
                }
            }
            if (info.failed) {
                mgroup = 'failed_infos';
                clr = 'red';
            } else {
                mgroup = 'good_infos';
                clr = participant.clr;
            }
            info.object_type = 'Info';
            nodes.push({
                id: my_node_id,
                label: info.type + ": " + String(info.id), dashes: true,
                title: info.type + ':' + String(info.id),
                group: mgroup,
                icon: {color: clr},
                font: {align: 'inside'},
                data: info
            });

            participant.object_type = 'Participant';
            if (participant_id > 0) {
                edges.push({
                    from: list_of_node_indx[from],
                    to: to,
                    dashes: true,
                    data: participant,
                    label: "participant: " + String(participant_id),
                    font: {size: 15, color: participant.clr, strokeWidth: 0, strokeColor: 'yellow', align: 'top'},
                    //arrows:'to', dashes:true,
                    title: "participant: " + String(participant_id) + '(' + participant.status + ')',
                });
            } else {
                edges.push({
                    from: list_of_node_indx[from],
                    to: to,
                    dashes: true
                });
            }
        }

        // create edges for transformation
        for (i = 0; i < net_structure.trans.length; i++) {
            tran = net_structure.trans[i];
            from = tran.info_in_id;
            to = tran.info_out_id;
            var from_n = map_infoid_to_infonum[from];
            var to_n = map_infoid_to_infonum[to];

            tran.object_type = 'Transmission';

            if (tran.failed) {
                rr = 200;
                gg = 100;
                bb = 100;
                mclr = 'rgb(' + String(rr) + ',' + String(gg) + ',' + String(bb) + ')';
            } else {
                //mclr='black'
                rr = 200;
                gg = 200;
                bb = 200;
                mclr = 'rgb(' + String(rr) + ',' + String(gg) + ',' + String(bb) + ')';
            }
            edges.push({
                from: from_n,
                to: to_n,
                arrows: 'to',
                dashes: true,
                title: 'transformation:' + String(tran.id) + '(' + String(tran.info_in_id) + '→' + String(tran.info_out_id) + ')',
                color: mclr,
                data: tran
            });
        }

        // This is needed to group networks according to roles
        // we used "father" for all the network and connect it
        // so the visualization will group things according to their role
        group_fathers = [];
        for (j = 0; j < roles.length; j++) {
            //group fathers of all practice networks
            count_nodes++;
            my_node_id = count_nodes;
            clr = roles_colors[j];
            gtitle = roles[j] + ' networks';

            nodes.push({
                id: my_node_id,
                label: gtitle,
                title: gtitle,
                group: 'group_father',
                font: {align: 'inside'},
                icon: {
                    face: 'FontAwesome',
                    code: '\uf0c2',
                    size: 120,
                    color: clr
                }
            });
            group_fathers[j] = my_node_id;
            // Connect group fathers to experiment node
            edges.push({
                from: 0,
                to: my_node_id,
                dashes: true,
                color: 'black',
                title: 'Experiment to Group ' + String(j)
            });
        }

        //connect network to correct source (or father)
        for (i = 0; i < net_structure.networks.length; i++) {
            net = net_structure.networks[i];
            count_nodes++;
            my_node_id = count_nodes;
            from = my_node_id;
            is_found = false;

            min_id = 99999999;
            // find the node with minimal id that belong to this network
            for (j = 0; j < net_structure.nodes.length; j++) {
                node = net_structure.nodes[j];
                if ((node.id <= min_id) && (node.network_id == net.id)) {
                    min_id = node.id;
                    to_min = list_of_node_indx[node.id];

                }
            }

            // find the source that belong to this network
            for (j = 0; j < net_structure.nodes.length; j++) {
                node = net_structure.nodes[j];
                if ((node.type.toLowerCase().search('source') > 0) && (node.network_id == net.id)) {
                    is_found = true;
                    to = list_of_node_indx[node.id];
                    break;
                }
            }

            if (net.property1 == 'True') { // assume that there is a feature in property1 that decide if a network is open or close
                mgroup = 'group_networks_open';
            } else {
                mgroup = 'group_networks_close';
            }

            father = group_fathers[networks_roles[net.id]]; // find father network
            clr = roles_colors[networks_roles[net.id]];
            net.object_type = 'Network';
            nodes.push({
                id: my_node_id,
                label: "network:" + String(net.id),
                title: "network: " + net.type + ':' + String(net.id) + ' (' + net.role + ')',
                group: mgroup,
                font: {align: 'inside'},
                icon: {
                    face: 'FontAwesome',
                    code: '\uf0c2',
                    color: clr
                },
                data: net

            });
            if (is_found) {
                edges.push({
                    from: from,
                    to: to,
                    color: 'black'
                });
            }
            //connect network to father
            edges.push({
                from: father,
                to: from,
                color: 'white',
                font: {align: 'inside'}
            });

        }

        return {nodes: nodes, edges: edges};
    }

    function destroy() {
        if (network !== null) {
            network.destroy();
            network = null;
        }
    }

    function draw() {

        destroy();

        var data = getnNetwork();

        // create a network
        var container = document.getElementById('mynetwork');

        var options = getOptions();
        network = new window.vis.Network(container, data, options);

        var stats = document.getElementById('element-details');

        var append_stats = function (el_ids, el_type) {
            for (var i = 0; i < el_ids.length; i++) {
                var node_id = el_ids[i];
                var node = network.body[el_type.toLowerCase()][node_id];
                if (node.options.title) {
                    if (i == 0) {
                        var title_el = document.createElement('h4');
                        title_el.textContent = el_type;
                        stats.appendChild(title_el);
                    }
                    var sub_title_el = document.createElement('h5');
                    sub_title_el.textContent = node.options.title;
                    stats.appendChild(sub_title_el);
                }
                if (node.options.data) {
                    var pre_el = document.createElement('pre');
                    pre_el.textContent = JSON.stringify(node.options.data, null, 2);
                    if (node.options.data.id && node.options.data.object_type) {
                        var custom_node = document.createElement('div');
                        custom_node.classList.add('node-details');
                        stats.appendChild(custom_node);
                        $(custom_node).load('/dashboard/node_details/' + node.options.data.object_type + '/' + String(node.options.data.id));
                    }
                    stats.appendChild(pre_el);
                }
            }
        };


        // add event listeners
        network.on('select', function (params) {
            if (params.nodes.length === 0 && params.edges.length === 0) {
                stats.style.display = 'none';
            } else {
                stats.innerHTML = '<button type="button" class="close" aria-label="Close" onclick="document.getElementById(\'element-details\').style.display= \'none\';">\n' +
                    '  <span aria-hidden="true">×</span>\n' +
                    '</button>';
                append_stats(params.nodes, 'Nodes');
                append_stats(params.edges, 'Edges');
                stats.style.display = 'block';
            }

        });
    }

    draw();


}

$('#order').click(function () {
    draw_network();
});

$('#sortBy, #max-networks, .network-input').change(function () {
    draw_network();
});

$('#search').keyup(function () {
    draw_network();
});


draw_network();