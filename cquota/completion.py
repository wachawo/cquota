#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shell completion scripts, generated from the argument parser."""
import argparse
from typing import Any, Dict, List

SHELLS = ("bash", "zsh")
FUNCTION_NAME = "complete_cquota"
# Values worth offering for options that accept more than a fixed set
VALUE_HINTS = {"--week": ("this", "last")}


def describe_argument(action: argparse.Action) -> Dict[str, Any]:
    flags = list(action.option_strings)
    values = action.choices or ()
    for flag in flags:
        values = VALUE_HINTS.get(flag, values)
    return {
        "flags":       flags,
        "help":        action.help or "",
        "takes_value": action.nargs != 0,
        "values":      tuple(values),
        "name":        action.metavar or action.dest.upper(),
    }


def list_commands(parser: argparse.ArgumentParser) -> Dict[str, Dict[str, Any]]:
    """Every command of the parser with its help and its arguments, in the order of declaration."""
    commands = {}
    for action in parser._actions:
        if not isinstance(action.choices, dict):
            continue
        helps = {choice.dest: choice.help or "" for choice in action._choices_actions}
        for name, command_parser in action.choices.items():
            arguments = [describe_argument(argument) for argument in command_parser._actions]
            commands[name] = {"help": helps.get(name, ""), "arguments": arguments}
    return commands


def list_flags(arguments: List[Dict[str, Any]]) -> List[str]:
    flags = []
    for argument in arguments:
        flags.extend(argument["flags"])
    return flags


def list_top_flags(parser: argparse.ArgumentParser) -> List[str]:
    flags = []
    for action in parser._actions:
        flags.extend(action.option_strings)
    return flags


def render_bash_values(name: str, arguments: List[Dict[str, Any]]) -> List[str]:
    """Case branches that complete the value of an argument, keyed by the word before it."""
    lines = []
    for argument in arguments:
        if not argument["takes_value"]:
            continue
        previous_words = argument["flags"] or [name]
        pattern = "|".join(f"{name}:{word}" for word in previous_words)
        lines.append(f"        {pattern}) candidates=\"{' '.join(argument['values'])}\" ;;")
    return lines


def render_bash(parser: argparse.ArgumentParser, default_command: str) -> str:
    commands = list_commands(parser)
    first_flags = list_top_flags(parser) + list_flags(commands[default_command]["arguments"])
    first_words = " ".join(list(commands) + list(dict.fromkeys(first_flags)))
    lines = [
        "# bash completion of cquota, load it with: source <(cquota completion bash)",
        f"{FUNCTION_NAME}() {{",
        "    local current=\"${COMP_WORDS[COMP_CWORD]}\"",
        "    local previous=\"${COMP_WORDS[COMP_CWORD-1]}\"",
        "    local command=\"${COMP_WORDS[1]}\"",
        "    local candidates=\"\"",
        "    if [ \"$COMP_CWORD\" -eq 1 ]; then",
        f"        COMPREPLY=($(compgen -W \"{first_words}\" -- \"$current\"))",
        "        return",
        "    fi",
        "    case \"$command\" in",
        f"        {'|'.join(commands)}) ;;",
        f"        *) command=\"{default_command}\" ;;",
        "    esac",
        "    case \"$command:$previous\" in",
    ]
    for name, command in commands.items():
        lines.extend(render_bash_values(name, command["arguments"]))
    for name, command in commands.items():
        lines.append(f"        {name}:*) candidates=\"{' '.join(list_flags(command['arguments']))}\" ;;")
    lines.extend([
        "    esac",
        "    COMPREPLY=($(compgen -W \"$candidates\" -- \"$current\"))",
        "}",
        f"complete -F {FUNCTION_NAME} cquota",
    ])
    return "\n".join(lines) + "\n"


def quote_zsh(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def render_zsh_specs(argument: Dict[str, Any]) -> List[str]:
    """The _arguments specs of one argument, one per flag."""
    value = ""
    if argument["takes_value"]:
        value = f":{argument['name']}:"
        if argument["values"]:
            value += f"({' '.join(argument['values'])})"
    if not argument["flags"]:
        return [quote_zsh(value)]
    description = ""
    if argument["help"]:
        description = "[" + argument["help"].replace("]", "\\]") + "]"
    return [quote_zsh(f"{flag}{description}{value}") for flag in argument["flags"]]


def render_zsh(parser: argparse.ArgumentParser, default_command: str) -> str:
    commands = list_commands(parser)
    lines = [
        "# zsh completion of cquota, load it after compinit with: source <(cquota completion zsh)",
        f"{FUNCTION_NAME}() {{",
        "    local -a commands",
        "    commands=(",
    ]
    for name, command in commands.items():
        lines.append("        " + quote_zsh(f"{name}:{command['help']}"))
    lines.extend([
        "    )",
        "    if (( CURRENT == 2 )) && [[ $words[2] != -* ]]; then",
        "        _describe 'command' commands",
        "        return",
        "    fi",
        f"    local command={default_command}",
        "    case $words[2] in",
        f"        {'|'.join(commands)})",
        "            command=$words[2]",
        "            shift words",
        "            (( CURRENT-- ))",
        "            ;;",
        "    esac",
        "    case $command in",
    ])
    for name, command in commands.items():
        lines.append(f"        {name})")
        lines.append("            _arguments \\")
        specs = []
        for argument in command["arguments"]:
            specs.extend(render_zsh_specs(argument))
        lines.append(" \\\n".join(f"                {spec}" for spec in specs))
        lines.append("            ;;")
    lines.extend([
        "    esac",
        "}",
        f"compdef {FUNCTION_NAME} cquota",
    ])
    return "\n".join(lines) + "\n"


def render_script(parser: argparse.ArgumentParser, shell: str, default_command: str) -> str:
    if shell == "zsh":
        return render_zsh(parser, default_command)
    return render_bash(parser, default_command)


def main():
    pass


if __name__ == "__main__":
    main()
