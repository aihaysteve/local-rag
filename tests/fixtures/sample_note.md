---
title: Kubernetes Deployment Guide
tags:
  - devops
  - kubernetes
  - infrastructure
aliases:
  - k8s guide
date: 2025-01-15
---

# Overview

This guide covers deploying applications to a Kubernetes cluster. See also [[Helm Charts|Helm]] for package management and [[Docker Basics]] for container fundamentals.

## Prerequisites

Before starting, ensure you have:
- A running cluster (see [[Cluster Setup]])
- kubectl installed and configured
- Basic understanding of YAML #yaml

## Deployment Strategies

### Rolling Updates

Rolling updates gradually replace old pods with new ones. This is the default strategy in Kubernetes.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
```

### Blue-Green Deployments

For zero-downtime releases, consider blue-green deployments. This approach runs two identical environments. #deployment #zero-downtime

## Monitoring

Use Prometheus and Grafana for monitoring your deployments. See [[Monitoring Setup]] for details.

![[architecture-diagram.png]]

Here is an inline code example with a hash: `color = "#ff0000"` which should not be treated as a tag.

```dataview
TABLE file.mtime AS "Modified"
FROM "DevOps"
SORT file.mtime DESC
```

## Resources

- Official Kubernetes documentation
- ![[deployment-checklist.pdf]]
- Community forums and #community-support channels
