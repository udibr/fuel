#!/usr/bin/env python
"""Fuel dataset conversion utility."""
import argparse
import os
import sys

import h5py

from fuel import converters
from fuel.converters.base import MissingInputFiles
from fuel.datasets import H5PYDataset


class CheckDirectoryAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if os.path.isdir(values):
            setattr(namespace, self.dest, values)
        else:
            raise ValueError('{} is not a existing directory'.format(values))


def main(args=None):
    """Entry point for `fuel-convert` script.

    This function can also be imported and used from Python.

    Parameters
    ----------
    args : iterable, optional (default: None)
        A list of arguments that will be passed to Fuel's conversion
        utility. If this argument is not specified, `sys.argv[1:]` will
        be used.

    """
    built_in_datasets = dict(converters.all_converters)
    parser = argparse.ArgumentParser(
        description='Conversion script for built-in datasets.')
    subparsers = parser.add_subparsers()
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "-d", "--directory", help="directory in which input files reside",
        type=str, default=os.getcwd())
    for name, subparser_fn in built_in_datasets.items():
        subparser = subparsers.add_parser(
            name, parents=[parent_parser],
            help='Convert the {} dataset'.format(name))
        subparser.add_argument(
            "-o", "--output-directory", help="where to save the dataset",
            type=str, default=os.getcwd(), action=CheckDirectoryAction)
        subparser_fn(subparser)

    args = parser.parse_args(args)
    args_dict = vars(args)
    try:
        func = args_dict.pop('func')
    except KeyError:
        parser.print_usage()
        parser.exit()
    try:
        output_paths = func(**args_dict)
    except MissingInputFiles as e:
        intro = "The following required files were not found:\n"
        message = "\n".join([intro] + ["   * " + f for f in e.filenames])
        message += "\n\nDid you forget to run fuel-download?"
        parser.error(message)

    # Tag the newly-created file(s) with H5PYDataset version and command-line
    # options
    for output_path in output_paths:
        h5file = h5py.File(output_path, 'a')
        interface_version = H5PYDataset.interface_version.encode('utf-8')
        h5file.attrs['h5py_interface_version'] = interface_version
        fuel_convert_version = converters.__version__.encode('utf-8')
        h5file.attrs['fuel_convert_version'] = fuel_convert_version
        command = [os.path.basename(sys.argv[0])] + sys.argv[1:]
        h5file.attrs['fuel_convert_command'] = (
            ' '.join(command).encode('utf-8'))
        h5file.flush()
        h5file.close()


if __name__ == "__main__":
    main()
