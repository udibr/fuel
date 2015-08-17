from __future__ import print_function
import argparse
import gzip
import mock
import os
import shutil
import struct
import tarfile
import tempfile

import h5py
import numpy
import six
from numpy.testing import assert_equal, assert_raises
from PIL import Image
from scipy.io import savemat
from six.moves import range, zip, cPickle

from fuel.converters.base import (fill_hdf5_file, check_exists,
                                  MissingInputFiles)
from fuel.converters import (binarized_mnist, caltech101_silhouettes,
                             iris, cifar10, cifar100, mnist, svhn)
from fuel.downloaders.caltech101_silhouettes import silhouettes_downloader
from fuel.downloaders.base import default_downloader

if six.PY3:
    getbuffer = memoryview
else:
    getbuffer = numpy.getbuffer


class TestFillHDF5File(object):
    def setUp(self):
        self.h5file = h5py.File(
            'file.hdf5', mode='w', driver='core', backing_store=False)
        self.train_features = numpy.arange(
            16, dtype='uint8').reshape((4, 2, 2))
        self.test_features = numpy.arange(
            8, dtype='uint8').reshape((2, 2, 2)) + 3
        self.train_targets = numpy.arange(
            4, dtype='float32').reshape((4, 1))
        self.test_targets = numpy.arange(
            2, dtype='float32').reshape((2, 1)) + 3

    def tearDown(self):
        self.h5file.close()

    def test_data(self):
        fill_hdf5_file(
            self.h5file,
            (('train', 'features', self.train_features, '.'),
             ('train', 'targets', self.train_targets),
             ('test', 'features', self.test_features),
             ('test', 'targets', self.test_targets)))
        assert_equal(self.h5file['features'],
                     numpy.vstack([self.train_features, self.test_features]))
        assert_equal(self.h5file['targets'],
                     numpy.vstack([self.train_targets, self.test_targets]))

    def test_dtype(self):
        fill_hdf5_file(
            self.h5file,
            (('train', 'features', self.train_features),
             ('train', 'targets', self.train_targets),
             ('test', 'features', self.test_features),
             ('test', 'targets', self.test_targets)))
        assert_equal(str(self.h5file['features'].dtype), 'uint8')
        assert_equal(str(self.h5file['targets'].dtype), 'float32')

    def test_multiple_length_error(self):
        train_targets = numpy.arange(8, dtype='float32').reshape((8, 1))
        assert_raises(ValueError, fill_hdf5_file, self.h5file,
                      (('train', 'features', self.train_features),
                       ('train', 'targets', train_targets)))

    def test_multiple_dtype_error(self):
        test_features = numpy.arange(
            8, dtype='float32').reshape((2, 2, 2)) + 3
        assert_raises(
            ValueError, fill_hdf5_file, self.h5file,
            (('train', 'features', self.train_features),
             ('test', 'features', test_features)))

    def test_multiple_shape_error(self):
        test_features = numpy.arange(
            16, dtype='uint8').reshape((2, 4, 2)) + 3
        assert_raises(
            ValueError, fill_hdf5_file, self.h5file,
            (('train', 'features', self.train_features),
             ('test', 'features', test_features)))


class TestMNIST(object):
    def setUp(self):
        MNIST_IMAGE_MAGIC = 2051
        MNIST_LABEL_MAGIC = 2049
        numpy.random.seed(9 + 5 + 2015)
        self.train_features_mock = numpy.random.randint(
            0, 256, (10, 1, 28, 28)).astype('uint8')
        self.train_targets_mock = numpy.random.randint(
            0, 10, (10, 1)).astype('uint8')
        self.test_features_mock = numpy.random.randint(
            0, 256, (10, 1, 28, 28)).astype('uint8')
        self.test_targets_mock = numpy.random.randint(
            0, 10, (10, 1)).astype('uint8')
        self.tempdir = tempfile.mkdtemp()
        self.train_images_path = os.path.join(
            self.tempdir, 'train-images-idx3-ubyte.gz')
        self.train_labels_path = os.path.join(
            self.tempdir, 'train-labels-idx1-ubyte.gz')
        self.test_images_path = os.path.join(
            self.tempdir, 't10k-images-idx3-ubyte.gz')
        self.test_labels_path = os.path.join(
            self.tempdir, 't10k-labels-idx1-ubyte.gz')
        self.wrong_images_path = os.path.join(self.tempdir, 'wrong_images.gz')
        self.wrong_labels_path = os.path.join(self.tempdir, 'wrong_labels.gz')
        with gzip.open(self.train_images_path, 'wb') as f:
            f.write(struct.pack('>iiii', *(MNIST_IMAGE_MAGIC, 10, 28, 28)))
            f.write(getbuffer(self.train_features_mock.flatten()))
        with gzip.open(self.train_labels_path, 'wb') as f:
            f.write(struct.pack('>ii', *(MNIST_LABEL_MAGIC, 10)))
            f.write(getbuffer(self.train_targets_mock.flatten()))
        with gzip.open(self.test_images_path, 'wb') as f:
            f.write(struct.pack('>iiii', *(MNIST_IMAGE_MAGIC, 10, 28, 28)))
            f.write(getbuffer(self.test_features_mock.flatten()))
        with gzip.open(self.test_labels_path, 'wb') as f:
            f.write(struct.pack('>ii', *(MNIST_LABEL_MAGIC, 10)))
            f.write(getbuffer(self.test_targets_mock.flatten()))
        with gzip.open(self.wrong_images_path, 'wb') as f:
            f.write(struct.pack('>iiii', *(2000, 10, 28, 28)))
        with gzip.open(self.wrong_labels_path, 'wb') as f:
            f.write(struct.pack('>ii', *(2000, 10)))

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_converter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('mnist')
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir,
            output_filename='mock_mnist.hdf5')
        mnist.fill_subparser(subparser)
        args = parser.parse_args(['mnist'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        h5file = h5py.File(filename, mode='r')
        assert_equal(
            h5file['features'][...],
            numpy.vstack(
                [self.train_features_mock, self.test_features_mock]))
        assert_equal(
            h5file['targets'][...],
            numpy.vstack([self.train_targets_mock, self.test_targets_mock]))
        assert_equal(str(h5file['features'].dtype), 'uint8')
        assert_equal(str(h5file['targets'].dtype), 'uint8')
        assert_equal(tuple(dim.label for dim in h5file['features'].dims),
                     ('batch', 'channel', 'height', 'width'))
        assert_equal(tuple(dim.label for dim in h5file['targets'].dims),
                     ('batch', 'index'))

    def test_converter_no_filename_no_dtype(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('mnist')
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir)
        mnist.fill_subparser(subparser)
        args = parser.parse_args(['mnist'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        assert_equal(os.path.basename(filename), 'mnist.hdf5')

    def test_converter_no_filename(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('mnist')
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir)
        mnist.fill_subparser(subparser)
        args = parser.parse_args(['mnist', '--dtype', 'bool'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        assert_equal(os.path.basename(filename), 'mnist_bool.hdf5')

    def test_wrong_image_magic(self):
        assert_raises(
            ValueError, mnist.read_mnist_images, self.wrong_images_path)

    def test_wrong_label_magic(self):
        assert_raises(
            ValueError, mnist.read_mnist_labels, self.wrong_labels_path)

    def test_read_image_bool(self):
        assert_equal(mnist.read_mnist_images(self.train_images_path, 'bool'),
                     self.train_features_mock >= 128)

    def test_read_image_float(self):
        rval = mnist.read_mnist_images(self.train_images_path, 'float32')
        assert_equal(rval, self.train_features_mock.astype('float32') / 255.)
        assert_equal(str(rval.dtype), 'float32')

    def test_read_image_value_error(self):
        assert_raises(ValueError, mnist.read_mnist_images,
                      self.train_images_path, 'int32')


class TestBinarizedMNIST(object):
    def setUp(self):
        numpy.random.seed(9 + 5 + 2015)
        self.train_mock = numpy.random.randint(0, 2, (5, 784))
        self.valid_mock = numpy.random.randint(0, 2, (5, 784))
        self.test_mock = numpy.random.randint(0, 2, (5, 784))
        self.tempdir = tempfile.mkdtemp()
        numpy.savetxt(
            os.path.join(self.tempdir, 'binarized_mnist_train.amat'),
            self.train_mock)
        numpy.savetxt(
            os.path.join(self.tempdir, 'binarized_mnist_valid.amat'),
            self.valid_mock)
        numpy.savetxt(
            os.path.join(self.tempdir, 'binarized_mnist_test.amat'),
            self.test_mock)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_converter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('binarized_mnist')
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir,
            output_filename='mock_binarized_mnist.hdf5')
        binarized_mnist.fill_subparser(subparser)
        args = parser.parse_args(['binarized_mnist'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        h5file = h5py.File(filename, mode='r')
        assert_equal(h5file['features'][...],
                     numpy.vstack([self.train_mock, self.valid_mock,
                                   self.test_mock]).reshape((-1, 1, 28, 28)))
        assert_equal(str(h5file['features'].dtype), 'uint8')
        assert_equal(tuple(dim.label for dim in h5file['features'].dims),
                     ('batch', 'channel', 'height', 'width'))


class TestCIFAR10(object):
    def setUp(self):
        numpy.random.seed(9 + 5 + 2015)
        self.train_features_mock = [
            numpy.random.randint(0, 256, (10, 3, 32, 32)).astype('uint8')
            for i in range(5)]
        self.train_targets_mock = [
            numpy.random.randint(0, 10, (10,)).astype('uint8')
            for i in range(5)]
        self.test_features_mock = numpy.random.randint(
            0, 256, (10, 3, 32, 32)).astype('uint8')
        self.test_targets_mock = numpy.random.randint(
            0, 10, (10,)).astype('uint8')
        self.tempdir = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(self.tempdir)
        os.mkdir('cifar-10-batches-py')
        for i, (x, y) in enumerate(zip(self.train_features_mock,
                                       self.train_targets_mock)):
            filename = os.path.join(
                'cifar-10-batches-py', 'data_batch_{}'.format(i + 1))
            with open(filename, 'wb') as f:
                cPickle.dump({'data': x, 'labels': y}, f)
        filename = os.path.join('cifar-10-batches-py', 'test_batch')
        with open(filename, 'wb') as f:
            cPickle.dump({'data': self.test_features_mock,
                          'labels': self.test_targets_mock},
                         f)
        with tarfile.open('cifar-10-python.tar.gz', 'w:gz') as tar_file:
            tar_file.add('cifar-10-batches-py')
        os.chdir(cwd)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_converter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('cifar10')
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir,
            output_filename='mock_cifar10.hdf5')
        cifar10.fill_subparser(subparser)
        args = parser.parse_args(['cifar10'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        h5file = h5py.File(filename, mode='r')
        assert_equal(
            h5file['features'][...],
            numpy.vstack(
                self.train_features_mock + [self.test_features_mock]))
        assert_equal(
            h5file['targets'][...],
            numpy.hstack(self.train_targets_mock +
                         [self.test_targets_mock]).reshape((-1, 1)))
        assert_equal(str(h5file['features'].dtype), 'uint8')
        assert_equal(str(h5file['targets'].dtype), 'uint8')
        assert_equal(tuple(dim.label for dim in h5file['features'].dims),
                     ('batch', 'channel', 'height', 'width'))
        assert_equal(tuple(dim.label for dim in h5file['targets'].dims),
                     ('batch', 'index'))


class TestCIFAR100(object):
    def setUp(self):
        numpy.random.seed(9 + 5 + 2015)
        self.train_features_mock = numpy.random.randint(
            0, 256, (10, 3, 32, 32)).astype('uint8')
        self.train_fine_labels_mock = numpy.random.randint(
            0, 100, (10,)).astype('uint8')
        self.train_coarse_labels_mock = numpy.random.randint(
            0, 20, (10,)).astype('uint8')
        self.test_features_mock = numpy.random.randint(
            0, 256, (10, 3, 32, 32)).astype('uint8')
        self.test_fine_labels_mock = numpy.random.randint(
            0, 100, (10,)).astype('uint8')
        self.test_coarse_labels_mock = numpy.random.randint(
            0, 20, (10,)).astype('uint8')
        self.tempdir = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(self.tempdir)
        os.mkdir('cifar-100-python')
        filename = os.path.join('cifar-100-python', 'train')
        with open(filename, 'wb') as f:
            cPickle.dump({'data': self.train_features_mock.reshape((10, -1)),
                          'fine_labels': self.train_fine_labels_mock,
                          'coarse_labels': self.train_coarse_labels_mock}, f)
        filename = os.path.join('cifar-100-python', 'test')
        with open(filename, 'wb') as f:
            cPickle.dump({'data': self.test_features_mock.reshape((10, -1)),
                          'fine_labels': self.test_fine_labels_mock,
                          'coarse_labels': self.test_coarse_labels_mock}, f)
        with tarfile.open('cifar-100-python.tar.gz', 'w:gz') as tar_file:
            tar_file.add('cifar-100-python')
        os.chdir(cwd)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_converter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('cifar100')
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir,
            output_filename='mock_cifar100.hdf5')
        cifar100.fill_subparser(subparser)
        args = parser.parse_args(['cifar100'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        h5file = h5py.File(filename, mode='r')
        assert_equal(
            h5file['features'][...],
            numpy.vstack([self.train_features_mock, self.test_features_mock]))
        assert_equal(
            h5file['fine_labels'][...],
            numpy.hstack([self.train_fine_labels_mock,
                          self.test_fine_labels_mock]).reshape((-1, 1)))
        assert_equal(
            h5file['coarse_labels'][...],
            numpy.hstack([self.train_coarse_labels_mock,
                          self.test_coarse_labels_mock]).reshape((-1, 1)))
        assert_equal(str(h5file['features'].dtype), 'uint8')
        assert_equal(str(h5file['fine_labels'].dtype), 'uint8')
        assert_equal(str(h5file['coarse_labels'].dtype), 'uint8')
        assert_equal(tuple(dim.label for dim in h5file['features'].dims),
                     ('batch', 'channel', 'height', 'width'))
        assert_equal(tuple(dim.label for dim in h5file['fine_labels'].dims),
                     ('batch', 'index'))
        assert_equal(tuple(dim.label for dim in h5file['coarse_labels'].dims),
                     ('batch', 'index'))


class TestCalTech101Silhouettes(object):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_fill_subparser(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('caltech101_silhouettes')
        caltech101_silhouettes.fill_subparser(subparser)
        assert (parser.parse_args(['caltech101_silhouettes', '16']).func is
                caltech101_silhouettes.convert_silhouettes)

    def test_download_and_convert(self, size=16):
        tempdir = self.tempdir

        cwd = os.getcwd()
        os.chdir(tempdir)

        assert_raises(MissingInputFiles,
                      caltech101_silhouettes.convert_silhouettes,
                      size=16, directory=tempdir,
                      output_directory=tempdir)
        assert_raises(ValueError, silhouettes_downloader,
                      size=10, directory=tempdir)

        silhouettes_downloader(size=size, directory=tempdir)

        assert_raises(ValueError,
                      caltech101_silhouettes.convert_silhouettes,
                      size=10, directory=tempdir,
                      output_directory=tempdir)

        caltech101_silhouettes.convert_silhouettes(size=size,
                                                   directory=tempdir,
                                                   output_directory=tempdir)

        os.chdir(cwd)

        output_file = "caltech101_silhouettes{}.hdf5".format(size)
        output_file = os.path.join(tempdir, output_file)
        with h5py.File(output_file, 'r') as h5:
            assert h5['features'].shape == (8641, 1, size, size)
            assert h5['targets'].shape == (8641, 1)


class TestIris(object):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_fill_subparser(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('iris')
        iris.fill_subparser(subparser)
        assert parser.parse_args(['iris']).func is iris.convert_iris

    def test_download_and_convert(self):
        tempdir = self.tempdir

        cwd = os.getcwd()
        os.chdir(tempdir)

        assert_raises(IOError,
                      iris.convert_iris,
                      directory=tempdir,
                      output_directory=tempdir)

        default_downloader(
            directory=tempdir,
            urls=['https://archive.ics.uci.edu/ml/machine-learning-databases/'
                  'iris/iris.data'],
            filenames=['iris.data'])

        classes = {
            b'Iris-setosa': 0, b'Iris-versicolor': 1, b'Iris-virginica': 2}
        data = numpy.loadtxt(
            os.path.join(tempdir, 'iris.data'),
            converters={4: lambda x: classes[x]},
            delimiter=',')
        features = data[:, :-1].astype('float32')
        targets = data[:, -1].astype('uint8').reshape((-1, 1))

        iris.convert_iris(directory=tempdir,
                          output_directory=tempdir)

        os.chdir(cwd)

        output_file = "iris.hdf5"
        output_file = os.path.join(tempdir, output_file)
        with h5py.File(output_file, 'r') as h5:
            assert numpy.allclose(h5['features'], features)
            assert numpy.allclose(h5['targets'], targets)


class TestSVHN(object):
    def setUp(self):
        numpy.random.seed(9 + 5 + 2015)

        self.tempdir = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(self.tempdir)

        self.f1_mock = {}

        def make_mock_format_1(split):
            self.f1_mock[split] = {}
            self.f1_mock[split]['image'] = [
                numpy.random.randint(0, 256, (6, 6, 3)).astype('uint8'),
                numpy.random.randint(0, 256, (5, 5, 3)).astype('uint8')]
            other_sources = ('label', 'height', 'width', 'left', 'top')
            for source in other_sources:
                self.f1_mock[split][source] = [
                    numpy.random.randint(0, 4, (2,)).astype('uint8'),
                    # This ensures that label '10' is converted to label '1'.
                    10 * numpy.ones((1,)).astype('uint8')]

            with tarfile.open('{}.tar.gz'.format(split), 'w:gz') as tar_file:
                os.mkdir(split)
                for i, image in enumerate(self.f1_mock[split]['image']):
                    Image.fromarray(image).save(
                        os.path.join(split, '{}.png'.format(i + 1)))
                struct_path = os.path.join(split, 'digitStruct.mat')
                with h5py.File(struct_path, 'w') as f:
                    for source in other_sources:
                        suffixes = []
                        for i in range(2):
                            suffix = 'i1{}{}'.format(source, i)
                            suffixes.append([suffix.encode('utf8')])
                            name = 'digitStruct/{}'.format(suffix)
                            f[name] = [[self.f1_mock[split][source][0][i]]]
                        name = 'digitStruct/image_1/{}'.format(source)
                        f[name] = suffixes
                        name = 'digitStruct/image_2/{}'.format(source)
                        f[name] = [[self.f1_mock[split][source][1][0]]]
                    ref_dtype = h5py.special_dtype(ref=h5py.Reference)
                    bbox = f.create_dataset(
                        'digitStruct/bbox', (2, 1), dtype=ref_dtype)
                    bbox[...] = [[f['digitStruct/image_1'].ref],
                                 [f['digitStruct/image_2'].ref]]
                tar_file.add(split)

        for split in ('train', 'test', 'extra'):
            make_mock_format_1(split)

        self.f2_train_features_mock = numpy.random.randint(
            0, 256, (32, 32, 3, 10)).astype('uint8')
        self.f2_train_targets_mock = numpy.random.randint(
            0, 10, (10, 1)).astype('uint8')
        self.f2_test_features_mock = numpy.random.randint(
            0, 256, (32, 32, 3, 10)).astype('uint8')
        self.f2_test_targets_mock = numpy.random.randint(
            0, 10, (10, 1)).astype('uint8')
        self.f2_extra_features_mock = numpy.random.randint(
            0, 256, (32, 32, 3, 10)).astype('uint8')
        self.f2_extra_targets_mock = numpy.random.randint(
            0, 10, (10, 1)).astype('uint8')
        savemat('train_32x32.mat', {'X': self.f2_train_features_mock,
                                    'y': self.f2_train_targets_mock})
        savemat('test_32x32.mat', {'X': self.f2_test_features_mock,
                                   'y': self.f2_test_targets_mock})
        savemat('extra_32x32.mat', {'X': self.f2_extra_features_mock,
                                    'y': self.f2_extra_targets_mock})
        os.chdir(cwd)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_format_1_converter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('svhn')
        svhn.fill_subparser(subparser)
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir,
            output_filename='svhn_format_1.hdf5')
        args = parser.parse_args(['svhn', '1'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        h5file = h5py.File(filename, mode='r')

        expected_features = sum((self.f1_mock[split]['image']
                                 for split in ('train', 'test', 'extra')), [])
        for val, truth in zip(h5file['features'][...], expected_features):
            assert_equal(val, truth.transpose(2, 0, 1).flatten())

        expected_labels = sum((self.f1_mock[split]['label']
                               for split in ('train', 'test', 'extra')), [])
        for val, truth in zip(h5file['bbox_labels'][...], expected_labels):
            truth[truth == 10] = 0
            assert_equal(val, truth)

        expected_lefts = sum((self.f1_mock[split]['left']
                              for split in ('train', 'test', 'extra')), [])
        for val, truth in zip(h5file['bbox_lefts'][...], expected_lefts):
            assert_equal(val, truth)

    def test_format_2_converter(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser('svhn')
        svhn.fill_subparser(subparser)
        subparser.set_defaults(
            directory=self.tempdir, output_directory=self.tempdir,
            output_filename='svhn_format_2.hdf5')
        args = parser.parse_args(['svhn', '2'])
        args_dict = vars(args)
        func = args_dict.pop('func')
        filename, = func(**args_dict)
        h5file = h5py.File(filename, mode='r')
        assert_equal(
            h5file['features'][...],
            numpy.vstack([self.f2_train_features_mock.transpose(3, 2, 0, 1),
                          self.f2_test_features_mock.transpose(3, 2, 0, 1),
                          self.f2_extra_features_mock.transpose(3, 2, 0, 1)]))
        assert_equal(
            h5file['targets'][...],
            numpy.vstack([self.f2_train_targets_mock,
                          self.f2_test_targets_mock,
                          self.f2_extra_targets_mock]))
        assert_equal(str(h5file['features'].dtype), 'uint8')
        assert_equal(str(h5file['targets'].dtype), 'uint8')
        assert_equal(tuple(dim.label for dim in h5file['features'].dims),
                     ('batch', 'channel', 'height', 'width'))
        assert_equal(tuple(dim.label for dim in h5file['targets'].dims),
                     ('batch', 'index'))

    @mock.patch('fuel.converters.svhn.convert_svhn_format_1')
    def test_converter_default_filename(self, mock_converter_format_1):
        svhn.convert_svhn(1, './', './')
        mock_converter_format_1.assert_called_with(
            './', './', 'svhn_format_1.hdf5')

    def test_converter_error_wrong_format(self):
        assert_raises(ValueError, svhn.convert_svhn, 3, './', 'mock.hdf5')


def test_check_exists():
    try:
        directory = tempfile.mkdtemp()
        with open(os.path.join(directory, 'abcdef.txt'), 'w') as f:
            print('\n', file=f)

        @check_exists(required_files=['abcdef.txt'])
        def foo(directory, a=None, b=None):
            pass
        try:
            foo(directory)
        except MissingInputFiles:
            assert False, "MissingInputFiles raised when files present"

        @check_exists(required_files=['ghijkl.txt'])
        def bar(directory, c=None, d=None):
            pass

        assert_raises(MissingInputFiles, bar, directory)

        @check_exists(required_files=['abcdef.txt', 'ghijkl.txt'])
        def baz(directory, x, y=None):
            pass

        assert_raises(MissingInputFiles, baz, directory, 9)

        try:
            baz(directory, 9)
        except MissingInputFiles as e:
            assert e.filenames == ['ghijkl.txt']

        with open(os.path.join(directory, 'ghijkl.txt'), 'w') as f:
            print('\n\n', file=f)

        try:
            bar(directory)
            baz(directory, 44)
        except MissingInputFiles:
            assert False, "MissingInputFiles raised when files present"

    finally:
        os.remove(os.path.join(directory, 'abcdef.txt'))
        os.remove(os.path.join(directory, 'ghijkl.txt'))
        os.rmdir(directory)
