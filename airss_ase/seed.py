"""
Classes for preparing AIRSS seed
"""
from __future__ import absolute_import
import numpy as np
from ase import Atoms, Atom
import numbers
import collections
from castepinput import CellInput
from ase.constraints import FixConstraint, FixBondLengths
from six.moves import range


class TemplateAtoms(Atoms):
    """Subclass of ase.atoms.Atoms object. Template for generating random cells
    """

    def __init__(self, *args, **kwargs):
        """Initialise an TemplateAtoms for buildcell.
        Same arguments signature as ase.Atoms object

        Special attribute:
          build : BuildcellParam instance for storing parameter of buildcell

        An array of SingeAtomParam objects are added automatically.
        Each one can be retrieved/replaced with
          set_buildcell_tag
          get_buildcell_tag
        """
        super(TemplateAtoms, self).__init__(*args, **kwargs)
        self.build = BuildcellParam()
        # Construct tags for each Atom
        tags = []
        symbols = self.get_chemical_symbols()
        for i in range(len(self)):
            tag = SingeAtomParam()
            # Make independent tags initially
            tag.tagname = symbols[i] + str(i)
            tags.append(tag)

        self.new_array('buildtag', tags, dtype=object, shape=None)

    def set_atom_tag(self, tag, index):
        """Set buildcell tags for individual atom
        if the SingeAtomParam object has no tagname, set automatically"""
        if tag.tagname is None:
            tag.tagname = self.get_chemical_symbols()[index]
        self.arrays['buildtag'][index] = tag

    def get_atom_tag(self, index):
        """
        Return the buildcell tag for the atom of the index.
        Can be used for in-place change
        """
        return self.arrays['buildtag'][index]

    @property
    def atom_tags(self):
        return self.arrays['buildtag']

    def get_seed_lines(self):
        """
        Return a list of strings of the seed file
        """
        return get_seed_lines(self)

    def write_seed(self, fpath):
        """Write the seed to file"""
        with open(fpath, 'w') as fhandle:
            fhandle.write('\n'.join(self.get_seed_lines()))

    def get_seed(self):
        """Return the python object represent the cell"""
        return get_seed(self)

    def __getitem__(self, i):
        """Return a subset of the atoms.

        i -- scalar integer, list of integers, or slice object
        describing which atoms to return.

        If i is a scalar, return an Atom object. If i is a list or a
        slice, return an Atoms object with the same cell, pbc, and
        other associated info as the original Atoms object. The
        indices of the constraints will be shuffled so that they match
        the indexing in the subset returned.

        """

        if isinstance(i, numbers.Integral):
            natoms = len(self)
            if i < -natoms or i >= natoms:
                raise IndexError('Index out of range.')

            return TemplateAtom(atoms=self, index=i)
        elif isinstance(i, list) and len(i) > 0:
            # Make sure a list of booleans will work correctly and not be
            # interpreted at 0 and 1 indices.
            i = np.array(i)

        import copy

        conadd = []
        # Constraints need to be deepcopied, but only the relevant ones.
        for con in copy.deepcopy(self.constraints):
            if isinstance(con, (FixConstraint, FixBondLengths)):
                try:
                    con.index_shuffle(self, i)
                    conadd.append(con)
                except IndexError:
                    pass

        atoms = self.__class__(
            cell=self._cell,
            pbc=self._pbc,
            info=self.info,
            # should be communicated to the slice as well
            celldisp=self._celldisp)
        # TODO: Do we need to shuffle indices in adsorbate_info too?

        atoms.arrays = {}
        for name, a in self.arrays.items():
            atoms.arrays[name] = a[i].copy()

        atoms.constraints = conadd
        return atoms


def tagproperty(name, doc):
    """Set a tag-like property"""

    def getter(self):
        return self.get(name)

    def setter(self, value):
        self.type_registry.update({name: 'tag'})
        if value is True:
            self.set_tag(name)
        elif value is False:
            self.delete(name)

    def deleter(self):
        self.delete(name)

    return property(getter, setter, deleter, doc)


def genericproperty(name, doc):
    """Set a range-like property"""

    def getter(self):
        return self.get_prop(name)

    def setter(self, value):
        self.type_registry.update({name: 'generic'})
        self.set_prop(name, value)

    def deleter(self):
        self.delete_prop(name)

    return property(getter, setter, deleter, doc)


def rangeproperty(name, doc):
    def getter(self):
        return self.get_prop(name)

    def setter(self, value):
        if isinstance(value, (tuple, list)):
            if len(value) != 2:
                raise ValueError("A tuple/list of two element must be used.")
            if any([not isinstance(x, numbers.Number) for x in value]):
                raise ValueError("Both elements need to be a number")
        self.type_registry.update({name: 'range'})
        self.set_prop(name, value)

    def deleter(self):
        self.delete_prop(name)

    return property(getter, setter, deleter, doc)


def nestedrangeproperty(name, doc):
    def getter(self):
        return self.get_prop(name)

    def setter(self, value):
        if isinstance(value, (tuple, list)):
            if len(value) != 2:
                raise RuntimeError("A tuple/list of two element must be used.")
        self.type_registry.update({name: 'nested_range'})
        self.set_prop(name, value)

    def deleter(self):
        self.delete_prop(name)

    return property(getter, setter, deleter, doc)


class BuildcellParam(object):
    """
    A class for storing parameters for the Buldcell program
    """

    def __init__(self):
        self.data = dict()
        self.type_registry = dict()

    def clear_all(self):
        """Set all property to be None"""
        self.data.clear()

    def get_prop(self, value):
        return self.data.__getitem__(value)

    def set_prop(self, name, value):
        return self.data.__setitem__(name, value)

    def set_tag(self, tag):
        self.data.__setitem__(tag, '')

    def delete_prop(self, name):
        self.data.pop(name)

    def to_string(self):
        """Return the string that should go into the .cell file"""
        lines = []
        for key, value in self.data.items():
            name = key.upper()
            type_string = self.type_registry[key]
            if value is False or value is None:
                continue
            if name == 'FIX':
                continue
            if type_string == 'tag':
                lines.append("#{}".format(name))
            # Allow direct passing of string
            elif type_string == 'generic':
                lines.append("#{}={}".format(name, value))
                continue
            elif type_string in ('range', 'nested_range'):
                # Check if there is a dictionary to unpack
                # The value can be
                if not isinstance(value, (list, tuple)):
                    line = '#{}={}'.format(name, value)
                else:
                    # The value is a list/tuple
                    # is a simple range?
                    if all([isinstance(x, numbers.Number) for x in value]):
                        line = '#{}={}'.format(name, tuple2range(value))
                    # Deal with a nested range
                    else:
                        line = '#{}={}'.format(name, tuple2range(value[0]))
                        tokens = [line]
                        if value[1]:
                            for k_, v_ in value[1].items():
                                tokens.append(k_ + '=' + tuple2range(v_))
                        line = ' '.join(tokens)
                lines.append(line)

        return '\n'.join(lines) + '\n'

    fix = tagproperty('FIX', 'Fix the cell')
    cfix = tagproperty('CFIX', 'Fix the caxis')
    cluster = tagproperty('CLUSTER', 'We are predicting CLUSTER')
    nforms = genericproperty('NFORMS', 'Number of formula units')
    minsep = nestedrangeproperty('MINSEP', 'Minimum separation constraints')
    posamp = nestedrangeproperty('POSAMP', 'Position amplitudes')
    symmops = rangeproperty('SYMMOPS',
                            'Number of symmetry operation requested cell')
    minamp = rangeproperty('MINAMP', 'Minimum aplitude of randomisation')
    zamp = rangeproperty('ZAMP', 'Randomisation amplitude in Z')
    xamp = rangeproperty('XAMP', 'Randomisation amplitude in X')
    yamp = rangeproperty('YAMP', 'Randomisation amplitude in Y')
    angamp = rangeproperty('ANGAMP',
                           'Angular randomisation amplitude from fragments')
    sgrank = rangeproperty('SGRANK', 'Minimum rank of the spacegroup')
    species = nestedrangeproperty('SPECIES', 'Species to be put into the cell')
    varvol = genericproperty(
        'VARVOL', 'Target volume of cell with the original configuration')
    slack = rangeproperty(
        'SLACK', 'Slack the hard sphere potentials enforcing the MINSEP')
    overlap = rangeproperty(
        'OVERLAP', 'Threhold of the overlap for the hard sphere potentials')
    #focus = genericproperty('FOCUS', 'Focus on a specific compositions')
    compact = tagproperty('COMPACT', 'Compact the cell using Niggli reduction')
    cons = genericproperty('CONS', 'Parameter for cell shape constraint')
    natom = rangeproperty(
        'NATOM', 'Number of atoms in cell, if not explicitly defined')


class SingeAtomParam(object):
    """Paramter for a single auto"""

    def __init__(self, *args, **kwargs):
        self.prop_data = dict()
        self.type_registry = dict()
        self.disabled = False

    def clear_all(self):
        """Set all property to be None"""
        self.prop_data.clear()

    def get_prop(self, value):
        return self.prop_data.__getitem__(value)

    def set_prop(self, name, value):
        return self.prop_data.__setitem__(name, value)

    def set_tag(self, tag):
        self.prop_data.__setitem__(tag, '')

    def delete_prop(self, name):
        self.prop_data.pop(name)

    tagname = genericproperty('tagname', 'Name of the tag')
    posamp = rangeproperty('POSAMP', 'Position amplitude')
    minamp = rangeproperty('POSAMP', 'Minimum positional amplitude')
    zamp = rangeproperty('ZAMP', 'Amplitude in Z')
    xamp = rangeproperty('XAMP', 'Amplitude in X')
    yamp = rangeproperty('YAMP', 'Amplitude in Y')
    num = rangeproperty('NUM', 'Number of atoms/fragments')
    atatom = rangeproperty('ADATOM', 'Add atoms after making supercell')
    fix = tagproperty('FIX', 'FIX this atom')

    def get_append_string(self):
        """
        Return the per entry string for this atom to be appended after its
        line in POSITIONS_FRAC / POSITIONS_ABS block
        """
        if self.disabled is True:
            return ''

        tokens = []
        # Set the tag
        tagname = self.prop_data.get('tagname')
        if not tagname:
            raise ValueError('The tagname property must be set')

        tokens.append('# {} %'.format(self.prop_data['tagname']))
        for key, value in self.prop_data.items():
            if key == "tagname":
                continue

            type_string = self.type_registry[key]
            name = key.upper()

            # Process the value based on type string
            if type_string == 'tag':
                tokens.append(name)
            elif type_string == 'range':
                if isinstance(value, (list, tuple)):
                    tokens.append('{}={}-{}'.format(name, *value))
                else:
                    tokens.append('{}={}'.format(name, value))
            else:
                tokens.append("{}={}".format(name, value))

        string = ' '.join(tokens)
        return string


class TemplateAtom(Atom, SingeAtomParam):
    """
    Element atoms in a AIRSS seed
    """

    def __init__(self, *args, **kwargs):
        super(TemplateAtom, self).__init__(*args, **kwargs)
        SingeAtomParam.__init__(self, *args, **kwargs)
        if self.atoms is not None:
            self.prop_data = self.atoms.arrays['buildtag'][
                self.index].prop_data
            self.type_registry = self.atoms.arrays['buildtag'][
                self.index].type_registry


def tuple2range(value):
    """
    Return the string for a given value. If the value is a tuple
    make it a range.
    """
    if isinstance(value, (list, tuple)):
        return "{}-{}".format(value[0], value[1])
    else:
        return str(value)


def get_seed(atoms):
    cell = CellInput()

    # Prepare the cell out
    cell.set_cell(atoms.get_cell())

    # Prepare the positions
    if atoms.positions.size > 0:
        species = atoms.get_chemical_symbols()
        pos_line_tags = list(atoms.atom_tags)
        tags_lines = [tag.get_append_string() for tag in pos_line_tags]
        cell.set_positions(species, atoms.get_positions(), tags_lines)

    return cell


def get_seed_lines(atoms):
    """
    Write the seed to a file handle
    """
    cell = get_seed(atoms)
    lines = []
    lines.extend(cell.get_file_lines())
    lines.extend(atoms.build.to_string().split('\n'))
    return lines
