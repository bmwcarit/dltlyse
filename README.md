# DLT Analyser

A Python module and a collection of plugins to support analysis of DLT traces.

## Run dltlyse with docker

1. Build the docker image

```bash
git clone https://github.com/bmwcarit/dltlyse
cd dltlyse
docker build -t bmwcarit/dltlyse .
```

2. Run the dltlyse container

```bash
# Get the command line help
docker run -it --rm bmwcarit/dltlyse --help

# Run with with dlt file(s)
docker run -it --rm \
    -v "$(pwd):/workspace" \
    -w /workspace bmwcarit/dltlyse \
      <path-to>.dlt <second-path-to>.dlt

# To specify your own dltlyse plugins specify path to their folder:
docker run -it --rm \
    -v /path/to/plugins:/plugins \
    -v "$(pwd):/workspace" \
    -w /workspace \
    bmwcarit/dltlyse \
      -d /plugins <path-to>.dlt
```

## How it works

`dltlyse` reads all messages from given DLT trace file and passes each DLT message to  __call__ of all enabled plugins.
Plugin then decides if the message is interesting for it's purpose and collects data.

At start of each device lifecycle new_lifecycle is called and at the end
end_lifecycle is called, in this way the plugins can track when the device was
rebooted. It is guaranteed that all messages will belong to a lifecycle, so
new_lifecycle will be called before any DLT message is passed to __call__ and
end_lifecycle will be called after last message before there will be a call ro
report.

Then the report() method from each plugin is called after all DLT messages have been passed through all enabled plugins.
The report() method should set one or more results from the processing as well as write details into files.

# Writing custom plugins

`dltlyse` could be easily extended with custom plugins using simple plugin API. Just use the following code snipplet
as a template stored in the "plugins" directory:

```
from dltlyse.core.plugin_base import Plugin


class MyCustomPlugin(Plugin):
    """Does some custom job"""

    message_filters = ["XXX", "YYY"]

    def __call__(self, message):
        # will be called for each message where message.apid="XXX" and message.ctid="YYY":
        # do some stuff, save knowledge into self

    def new_lifecycle(self, ecu_id, lifecycle_id):
        # will be called each time the device starts up with incremental id

    def end_lifecycle(self, ecu_id, lifecycle_id):
        # will be called each time the device shuts down

    def report(self):
        # called at the end
        if self.good:
            self.add_result(message="Good result", attach=["somefile.txt"])
            # Attachment path is relative to extracted_files/ folder in results
        else:
            self.add_result(
                state="failure",
                message="This failed",
                stdout="Detailed log of failure",
            )
```

