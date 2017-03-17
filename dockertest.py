#!/usr/bin/env python
# -*- coding: utf-8 -*-


import docker
import pprint

client = docker.DockerClient(base_url='http://10.3.88.24:4243')
containers = client.containers.list()
for container in containers:
    pprint.pprint(container.attrs)
