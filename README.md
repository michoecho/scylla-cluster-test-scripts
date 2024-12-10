# "Architecture"

`prov/ec2` and `prov/ec2-ondemand` contain some [terraform configs](prov/ec2-ondemand/main.tf) (using spot instances and on-demand instances respectively) with parameters which have to be filled in, such as AMI identifiers, cluster size, instance types, etc.

Files in `configs` contain the parameters, in form of YAML files. One of the files should contain the AWS credentials (`access_key` and `secret_key`), the name of the owner (`owner`, this becomes a tag in AWS and lets people find out who created the resources), and a path to the initial SSH keys that will be copied to the nodes to allow connecting to them(`public_key_path` and `private_key_path`).

`prov/provision-terraform` (a CLI wrapper around `prov/terraform.py`) takes the terraform template and the config files and calls `terraform` on them, (which will create all the AWS instances, security groups, networks, tags, etc). For example, when investigating github issue number 4504, you might do:

```
prov/provision-terraform 4504 prov/ec2-ondemand configs/credentials.yaml configs/4504.yml
```

The first argument to `prov/provision-terraform` is the "deployment name". The command will 
create a directory with that name, and this directory will contain the state of this deployment,
which includes `tf` (terraform's state, needed to handle later changes to the cloud resources), 
`ssh_config` which is a SSH config file which can be used to connect to the cluster by node names,
and `inventory` which is an Ansible `inventory` file describing the cluster.

`prov/provision-terraform` can be re-ran on the same "deployment" after updating the configs or the templates.
(So you can, for example, change the number of nodes in an existing deployment).

[bench/utils.py](bench/utils.py) contains a `Deployment` class which can be constructed on from that state directory,
and has many methods which run various commands on the cluster, like setting up scylla-monitoring,
installing cassandra-stress, modifying Scylla configs, starting and stopping Scylla nodes, starting, stopping, snapshotting and restoring Scylla nodes, starting and stopping cassandra-stress, downloading monitoring snapshots, running arbitrary shell commands and copying arbitrary files, and so on.

And then I just write various scripts around these utils.

For example, when investigating a performance issue, I could do something like:
```
prov/provision-terraform 4504 prov/ec2-ondemand configs/credentials.yaml configs/4504.yml
python setup.py 4504
python populate_and_snapshot.py 4504
python restore_and_run_load.py 4504
vim tweak_settings.py
python tweak_settings.py 4504
python restore_and_run_load.py 4504
vim tweak_settings.py
python tweak_settings.py 4504
python restore_and_run_load.py 4504
...
# Remember to clean up at the end:
prov/deprovision_terraform 4504
```

See [run.py](run.py) for an example of a script that I just happened to have open when I was writing this README.

Also, `bin/ssh` is just a wrapper around SSH which uses the created `ssh_config` file by default.

So you can interactively, ssh into a node by doing `bin/ssh 4504 server-0`, or interactively copy files by doing `rsync -e 'bin/ssh 4504' server-0:/source/file /local/target/file`. Useful if you want to look at `htop` or at `journalctl`.
