# Sublime LLDB

# Setting targets

The run command will list targets defined in a project file. Example:

```
{
    "folders":
    [
        {
            "path": "."
        }
    ],
    "settings":
    {
        "sublime-lldb":
        {
            "targets":
            [
                {
                    "executable_path": "/path/to/executable",
                    "arguments": ["arg1", "arg2"],
                    "environment": {
                        "PATH": "/usr/local/bin",
                    }
                },
                {
                    "executable_path": "/path/to/another/executable",
                },
            ]
        }
    }
}
```
