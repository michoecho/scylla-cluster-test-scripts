import json
import os
import sys
import subprocess
import shutil

def apply(deployment_name, terraform_plan, config):
    config['private_key_path'] = os.path.realpath(config['private_key_path'])
    config['public_key_path'] = os.path.realpath(config['public_key_path'])
    config['deployment_name'] = deployment_name

    subprocess.check_call(f"rsync -r --mkpath {terraform_plan}/ {deployment_name}/tf", shell=True)
    tf_dir = f"{deployment_name}/tf"

    with open(f'{tf_dir}/tfvars.candidate.json', 'w') as f:
        json.dump(config, f);

    tf_env = {
        "shell": True,
        "cwd": f"{tf_dir}",
    }

    cmd = f'terraform init'
    subprocess.check_call(cmd, **tf_env)

    cmd = f'terraform apply -var-file tfvars.candidate.json'
    subprocess.check_call(cmd, **tf_env)    

    shutil.move(f"{tf_dir}/tfvars.candidate.json", f"{tf_dir}/tfvars.json")

    with open(f"{tf_dir}/terraform.tfstate") as f:
        state = json.load(f)

    def debug(text):
      print(text)
      return ''

    import jinja2
    jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )
    jinja_env.filters['debug']=debug
    ssh_template = jinja_env.get_template("ssh_config")
    inventory_template = jinja_env.get_template("inventory")

    instances = {}
    for resource in state["resources"]:
        if resource["type"] in ["aws_instance", "aws_spot_instance_request"]:
            group = resource["name"]
            instances.setdefault(group, [])
            for i, instance in enumerate(resource["instances"]):
                instances[group].append({
                    "public_ip": instance["attributes"]["public_ip"],
                    "private_ip": instance["attributes"]["private_ip"],
                })

    with open(f'{deployment_name}/ssh_config', 'w') as ssh_config_file:
        ssh_config_file.write(ssh_template.render(instances=instances, var=config))
    with open(f'{deployment_name}/inventory', 'w') as inventory_file:
        inventory_file.write(inventory_template.render(instances=instances, var=config, seed=instances["server"][0]["private_ip"]))

def destroy(deployment_name):
    tf_dir = f"{deployment_name}/tf"
    tf_env = {
        "shell": True,
        "cwd": tf_dir,
    }
   
    varfile = os.path.realpath(f"{tf_dir}/tfvars.json")
    if not os.path.isfile(varfile):
        varfile = os.path.realpath(f"{tf_dir}/tfvars.candidate.json")

    cmd = f'terraform destroy -var-file {varfile}'
    subprocess.check_call(cmd, **tf_env)

    shutil.rmtree(f"{deployment_name}")
