# Copyright 2022 DeepMind Technologies Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for MuJoCo Python bindings."""

import contextlib
import copy
import pickle
import sys

from absl.testing import absltest
from absl.testing import parameterized
import mujoco
import numpy as np

TEST_XML = r"""
<mujoco model="test">
  <compiler coordinate="local" angle="radian" eulerseq="xyz"/>
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <visual>
    <global fovy="50" />
    <quality shadowsize="51" />
  </visual>
  <worldbody>
    <geom name="myplane" type="plane" size="10 10 1"/>
    <body pos="0 0 0.1">
      <geom name="mybox" type="box" size="0.1 0.1 0.1" mass="0.25"/>
      <freejoint name="myfree"/>
    </body>
    <body>
      <inertial pos="0 0 0" mass="1" diaginertia="1 1 1"/>
      <site pos="0 0 -1" name="mysite" type="sphere"/>
      <joint type="hinge" axis="0 1 0"/>
    </body>
    <body>
      <inertial pos="0 0 0" mass="1" diaginertia="1 1 1"/>
      <joint name="myball" type="ball"/>
    </body>
    <body mocap="true" pos="42 0 42">
      <geom type="sphere" size="0.1"/>
    </body>
  </worldbody>
</mujoco>
"""

TEST_XML_SENSOR = r"""
<mujoco model="test">
  <worldbody>
    <geom name="myplane" type="plane" size="10 10 1"/>
  </worldbody>
  <sensor>
    <user objtype="geom" objname="myplane"
          datatype="real" needstage="vel" dim="1"/>
  </sensor>
</mujoco>
"""


@contextlib.contextmanager
def temporary_callback(setter, callback):
  setter(callback)
  yield
  setter(None)


class MuJoCoBindingsTest(parameterized.TestCase):

  def setUp(self):
    super().setUp()
    self.model: mujoco.MjModel = mujoco.MjModel.from_xml_string(TEST_XML)
    self.data = mujoco.MjData(self.model)

  def test_load_xml_can_handle_name_clash(self):
    xml_1 = r"""
<mujoco>
  <worldbody>
    <geom name="plane" type="plane" size="1 1 1"/>
    <include file="model_.xml"/>
    <include file="model__.xml"/>
  </worldbody>
</mujoco>"""
    xml_2 = rb"""<mujoco><geom name="box" type="box" size="1 1 1"/></mujoco>"""
    xml_3 = rb"""<mujoco><geom name="ball" type="sphere" size="1"/></mujoco>"""
    model = mujoco.MjModel.from_xml_string(
        xml_1, {'model_.xml': xml_2, 'model__.xml': xml_3})
    self.assertEqual(
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, 'plane'), 0)
    self.assertEqual(
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, 'box'), 1)
    self.assertEqual(
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, 'ball'), 2)

  def test_can_read_array(self):
    np.testing.assert_array_equal(
        self.model.body_pos,
        [[0, 0, 0], [0, 0, 0.1], [0, 0, 0], [0, 0, 0], [42.0, 0, 42.0]])

  def test_can_set_array(self):
    self.data.qpos = 0.12345
    np.testing.assert_array_equal(
        self.data.qpos, [0.12345]*len(self.data.qpos))

  def test_array_is_a_view(self):
    qpos_ref = self.data.qpos
    self.data.qpos = 0.789
    np.testing.assert_array_equal(
        qpos_ref, [0.789]*len(self.data.qpos))

  def test_array_keeps_struct_alive(self):
    model = mujoco.MjModel.from_xml_string(TEST_XML)
    qpos0 = model.qpos0
    qpos_spring = model.qpos_spring

    # This only fails reliably under ASAN, which detects heap-use-after-free.
    # However, often the assertEqual is enough since the memory block is
    # already reused between mjModel deallocation and the subsequent read.
    qpos0[:] = 1
    del model
    self.assertEqual(qpos0[0], 1)

    # When running under test coverage tools, the refcount of objects can be
    # higher than normal. To take this into account, we first measure the
    # refcount of a dummy object with no other referrer.
    dummy = []
    base_refcount = sys.getrefcount(dummy) - 1

    # Here `base` is actually a PyCapsule that holds the raw mjModel* rather
    # than the actual MjModel wrapper object itself.
    capsule = qpos0.base
    self.assertEqual(sys.getrefcount(capsule) - base_refcount, 3)
    del qpos0
    self.assertEqual(sys.getrefcount(capsule) - base_refcount, 2)
    del qpos_spring
    self.assertEqual(sys.getrefcount(capsule) - base_refcount, 1)

  def test_named_indexing_geom_size(self):
    box_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, 'mybox')
    self.assertIs(self.model.geom('mybox'), self.model.geom(box_id))
    self.assertIs(self.model.geom('mybox').size, self.model.geom(box_id).size)
    self.assertEqual(self.model.geom('mybox').size.shape, (3,))

    # Test that the indexer is returning a view into the underlying struct.
    size_from_indexer = self.model.geom('mybox').size
    self.model.geom_size[box_id] = [7, 11, 13]
    np.testing.assert_array_equal(size_from_indexer, [7, 11, 13])
    self.model.geom('mybox').size = [5, 3, 2]
    np.testing.assert_array_equal(self.model.geom_size[box_id], [5, 3, 2])

  def test_named_indexing_geom_quat(self):
    box_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, 'mybox')
    self.assertIs(self.model.geom('mybox'), self.model.geom(box_id))
    self.assertIs(self.model.geom('mybox').quat, self.model.geom(box_id).quat)
    self.assertEqual(self.model.geom('mybox').quat.shape, (4,))

    # Test that the indexer is returning a view into the underlying struct.
    quat_from_indexer = self.model.geom('mybox').quat
    self.model.geom_quat[box_id] = [5, 10, 15, 20]
    np.testing.assert_array_equal(quat_from_indexer, [5, 10, 15, 20])
    self.model.geom('mybox').quat = [12, 9, 6, 3]
    np.testing.assert_array_equal(self.model.geom_quat[box_id], [12, 9, 6, 3])

  def test_named_indexing_ragged_qpos(self):
    balljoint_id = mujoco.mj_name2id(
        self.model, mujoco.mjtObj.mjOBJ_JOINT, 'myball')
    self.assertIs(self.data.joint('myball'), self.data.joint(balljoint_id))
    self.assertIs(self.data.joint('myball').qpos,
                  self.data.joint(balljoint_id).qpos)
    self.assertEqual(self.data.joint('myball').qpos.shape, (4,))

    # Test that the indexer is returning a view into the underlying struct.
    qpos_from_indexer = self.data.joint('myball').qpos
    qpos_idx = self.model.jnt_qposadr[balljoint_id]
    self.data.qpos[qpos_idx:qpos_idx+4] = [4, 5, 6, 7]
    np.testing.assert_array_equal(qpos_from_indexer, [4, 5, 6, 7])
    self.data.joint('myball').qpos = [9, 8, 7, 6]
    np.testing.assert_array_equal(self.data.qpos[qpos_idx:qpos_idx+4],
                                  [9, 8, 7, 6])

  def test_named_indexing_ragged2d_cdof(self):
    freejoint_id = mujoco.mj_name2id(
        self.model, mujoco.mjtObj.mjOBJ_JOINT, 'myfree')
    self.assertIs(self.data.joint('myfree'), self.data.joint(freejoint_id))
    self.assertIs(self.data.joint('myfree').cdof,
                  self.data.joint(freejoint_id).cdof)
    self.assertEqual(self.data.joint('myfree').cdof.shape, (6, 6))

    # Test that the indexer is returning a view into the underlying struct.
    cdof_from_indexer = self.data.joint('myfree').cdof
    dof_idx = self.model.jnt_dofadr[freejoint_id]
    self.data.cdof[dof_idx:dof_idx+6, :] = np.reshape(range(36), (6, 6))
    np.testing.assert_array_equal(cdof_from_indexer,
                                  np.reshape(range(36), (6, 6)))
    self.data.joint('myfree').cdof = 42
    np.testing.assert_array_equal(self.data.cdof[dof_idx:dof_idx+6], [[42]*6]*6)

  def test_addresses_differ_between_structs(self):
    model2 = mujoco.MjModel.from_xml_string(TEST_XML)
    data2 = mujoco.MjData(model2)

    self.assertGreater(self.model._address, 0)
    self.assertGreater(self.data._address, 0)
    self.assertGreater(model2._address, 0)
    self.assertGreater(data2._address, 0)
    self.assertLen({self.model._address, self.data._address,
                    model2._address, data2._address}, 4)

  def test_mjmodel_can_read_and_write_opt(self):
    self.assertEqual(self.model.opt.timestep, 0.002)
    np.testing.assert_array_equal(self.model.opt.gravity, [0, 0, -9.81])

    opt = self.model.opt
    self.model.opt.timestep = 0.001
    self.assertEqual(opt.timestep, 0.001)

    gravity = opt.gravity
    self.model.opt.gravity[1] = 0.1
    np.testing.assert_array_equal(gravity, [0, 0.1, -9.81])
    self.model.opt.gravity = 0.2
    np.testing.assert_array_equal(gravity, [0.2, 0.2, 0.2])

  def test_mjmodel_can_read_and_write_stat(self):
    self.assertNotEqual(self.model.stat.meanmass, 0)

    stat = self.model.stat
    self.model.stat.meanmass = 1.2
    self.assertEqual(stat.meanmass, 1.2)

  def test_mjmodel_can_read_and_write_vis(self):
    self.assertEqual(self.model.vis.quality.shadowsize, 51)

    self.model.vis.quality.shadowsize = 100
    self.assertEqual(self.model.vis.quality.shadowsize, 100)

  def test_mjmodel_can_access_names_directly(self):
    # mjModel offers direct access to names array, to allow usecases other than
    # id2name
    model_name = str(self.model.names[0:self.model.names.find(b'\0')], 'utf-8')
    self.assertEqual(model_name, 'test')

    start_index = self.model.name_geomadr[0]
    end_index = self.model.names.find(b'\0', start_index)
    geom_name = str(self.model.names[start_index:end_index], 'utf-8')
    self.assertEqual(geom_name, 'myplane')

  def test_mjmodel_names_doesnt_copy(self):
    names = self.model.names
    self.assertIs(names, self.model.names)

  def test_vis_global_exposed_as_global_(self):
    self.assertEqual(self.model.vis.global_.fovy, 50)
    self.model.vis.global_.fovy = 100
    self.assertEqual(self.model.vis.global_.fovy, 100)

  def test_mjoption_can_make_default(self):
    opt = mujoco.MjOption()
    self.assertEqual(opt.timestep, 0.002)
    np.testing.assert_array_equal(opt.gravity, [0, 0, -9.81])

  def test_mjoption_can_copy(self):
    opt1 = mujoco.MjOption()
    opt1.timestep = 0.001
    opt1.gravity = 2

    opt2 = copy.copy(opt1)
    self.assertEqual(opt2.timestep, 0.001)
    np.testing.assert_array_equal(opt2.gravity, [2, 2, 2])

    # Make sure opt2 is actually a copy.
    opt1.timestep = 0.005
    opt1.gravity = 5
    self.assertEqual(opt2.timestep, 0.001)
    np.testing.assert_array_equal(opt2.gravity, [2, 2, 2])

  def test_mjmodel_can_copy(self):
    model_copy = copy.copy(self.model)

    self.assertEqual(
        mujoco.mj_id2name(model_copy, mujoco.mjtObj.mjOBJ_JOINT, 0),
        'myfree')

    self.assertEqual(
        mujoco.mj_id2name(model_copy, mujoco.mjtObj.mjOBJ_GEOM, 0),
        'myplane')
    self.assertEqual(
        mujoco.mj_id2name(model_copy, mujoco.mjtObj.mjOBJ_GEOM, 1),
        'mybox')

    # Make sure it's a copy.
    self.model.geom_size[1] = 0.5
    np.testing.assert_array_equal(self.model.geom_size[1], [0.5, 0.5, 0.5])
    np.testing.assert_array_equal(model_copy.geom_size[1], [0.1, 0.1, 0.1])

  def test_assets_array_filename_too_long(self):
    # Longest allowed filename (excluding null byte)
    limit = mujoco.mjMAXVFSNAME - 1
    contents = b'<mujoco/>'
    valid_filename = 'a' * limit
    mujoco.MjModel.from_xml_path(valid_filename, {valid_filename: contents})
    invalid_filename = 'a' * (limit + 1)
    expected_message = (
        f'Filename length 1000 exceeds 999 character limit: {invalid_filename}')
    with self.assertRaisesWithLiteralMatch(ValueError, expected_message):
      mujoco.MjModel.from_xml_path(invalid_filename,
                                   {invalid_filename: contents})

  def test_mjdata_can_copy(self):
    self.data.qpos = [0, 0, 0.1*np.sqrt(2) - 0.001,
                      np.cos(np.pi/8), np.sin(np.pi/8), 0, 0, 0,
                      1, 0, 0, 0]
    mujoco.mj_forward(self.model, self.data)

    data_copy = copy.copy(self.data)
    self.assertEqual(data_copy.ncon, 2)

    # Make sure it's a copy.
    mujoco.mj_resetData(self.model, self.data)
    mujoco.mj_forward(self.model, self.data)
    mujoco.mj_forward(self.model, data_copy)
    self.assertEqual(self.data.ncon, 4)
    self.assertEqual(data_copy.ncon, 2)

    mujoco.mj_resetData(self.model, data_copy)
    mujoco.mj_forward(self.model, data_copy)
    self.assertEqual(data_copy.ncon, 4)

  def test_mjdata_can_read_warning_array(self):
    warnings = self.data.warning
    self.assertLen(warnings, mujoco.mjtWarning.mjNWARNING)
    self.data.qpos[0] = float('NaN')
    mujoco.mj_checkPos(self.model, self.data)
    self.assertEqual(warnings[mujoco.mjtWarning.mjWARN_BADQPOS].number, 1)

  def test_mjcontact_can_copy(self):
    mujoco.mj_forward(self.model, self.data)

    contact_copy = []
    for i in range(4):
      contact_copy.append(copy.copy(self.data.contact[i]))
    # Sort contacts in anticlockwise order
    contact_copy = sorted(
        contact_copy, key=lambda x: np.arctan2(x.pos[1], x.pos[0]))
    np.testing.assert_allclose(contact_copy[0].pos[:2], [-0.1, -0.1])
    np.testing.assert_allclose(contact_copy[1].pos[:2], [0.1, -0.1])
    np.testing.assert_allclose(contact_copy[2].pos[:2], [0.1, 0.1])
    np.testing.assert_allclose(contact_copy[3].pos[:2], [-0.1, 0.1])

    # Make sure they're actually copies.
    for i in range(4):
      self.data.contact[i].pos[:2] = 55
    np.testing.assert_allclose(self.data.contact[0].pos[:2], [55, 55])
    np.testing.assert_allclose(self.data.contact[1].pos[:2], [55, 55])
    np.testing.assert_allclose(self.data.contact[2].pos[:2], [55, 55])
    np.testing.assert_allclose(self.data.contact[3].pos[:2], [55, 55])
    np.testing.assert_allclose(contact_copy[0].pos[:2], [-0.1, -0.1])
    np.testing.assert_allclose(contact_copy[1].pos[:2], [0.1, -0.1])
    np.testing.assert_allclose(contact_copy[2].pos[:2], [0.1, 0.1])
    np.testing.assert_allclose(contact_copy[3].pos[:2], [-0.1, 0.1])

  def test_mj_step(self):
    displacement = 0.25
    self.data.qpos[2] += displacement
    mujoco.mj_forward(self.model, self.data)

    gravity = -self.model.opt.gravity[2]
    expected_contact_time = np.sqrt(2 * displacement / gravity)

    # Grab a reference to the contacts upfront so that we know that they're
    # a view into mjData rather than a copy.
    contact = self.data.contact[:4]

    self.model.opt.timestep = 2**-9  # 0.001953125; allows exact comparisons
    self.assertEqual(self.data.time, 0)
    while self.data.time < expected_contact_time:
      self.assertEqual(self.data.ncon, 0)
      prev_time = self.data.time
      mujoco.mj_step(self.model, self.data)
      self.assertEqual(self.data.time, prev_time + self.model.opt.timestep)

    mujoco.mj_forward(self.model, self.data)
    self.assertEqual(self.data.ncon, 4)

    # Sort contacts in anticlockwise order
    sorted_contact = sorted(
        contact, key=lambda x: np.arctan2(x.pos[1], x.pos[0]))
    np.testing.assert_allclose(sorted_contact[0].pos[:2], [-0.1, -0.1])
    np.testing.assert_allclose(sorted_contact[1].pos[:2], [0.1, -0.1])
    np.testing.assert_allclose(sorted_contact[2].pos[:2], [0.1, 0.1])
    np.testing.assert_allclose(sorted_contact[3].pos[:2], [-0.1, 0.1])

  def test_mj_step_multiple(self):
    self.model.opt.timestep = 2**-9  # 0.001953125; allows exact comparisons
    self.assertEqual(self.data.time, 0)
    for _ in range(10):
      prev_time = self.data.time
      mujoco.mj_step(self.model, self.data, nstep=7)
      self.assertEqual(self.data.time, prev_time + 7 * self.model.opt.timestep)
    self.assertIn('Optionally, repeat nstep times.', mujoco.mj_step.__doc__)

  def test_mj_contact_list(self):
    self.assertLen(self.data.contact, self.model.nconmax)

    expected_pos = []
    for contact in self.data.contact:
      expected_pos.append(np.random.uniform(size=3))
      contact.pos = expected_pos[-1]
    np.testing.assert_array_equal(self.data.contact.pos, expected_pos)

    expected_friction = []
    for contact in self.data.contact:
      expected_friction.append(np.random.uniform(size=5))
      contact.friction = expected_friction[-1]
    np.testing.assert_array_equal(self.data.contact.friction, expected_friction)

    expected_H = []  # pylint: disable=invalid-name
    for contact in self.data.contact:
      expected_H.append(np.random.uniform(size=36))
      contact.H = expected_H[-1]
    np.testing.assert_array_equal(self.data.contact.H, expected_H)

  def test_mj_struct_list_equality(self):
    model2 = mujoco.MjModel.from_xml_string(TEST_XML)
    data2 = mujoco.MjData(model2)

    mujoco.mj_forward(self.model, self.data)
    self.assertEqual(self.data.ncon, 4)
    mujoco.mj_forward(model2, data2)
    self.assertEqual(data2.ncon, 4)
    self.assertEqual(data2.contact[:4], self.data.contact[:4])

    self.data.qpos[3:7] = [np.cos(np.pi/8), np.sin(np.pi/8), 0, 0]
    self.data.qpos[2] *= (np.sqrt(2) - 1) * 0.1 - 1e-6
    mujoco.mj_forward(self.model, self.data)
    self.assertEqual(self.data.ncon, 2)
    self.assertNotEqual(data2.contact[:2], self.data.contact[:2])

    # Check that we can compare slices of different lengths
    self.assertNotEqual(data2.contact[:2], self.data.contact[:4])

    # Check that comparing things of different types do not raise an error
    self.assertNotEqual(self.data.contact, self.data.warning)
    self.assertNotEqual(self.data.contact, 5)

  @parameterized.named_parameters([
      ('MjOption', mujoco.MjOption, 'tolerance'),
      ('MjWarningStat', mujoco.MjWarningStat, 'number'),
      ('MjTimerStat', mujoco.MjTimerStat, 'number'),
      ('MjSolverStat', mujoco.MjSolverStat, 'neval'),
      ('MjContact', mujoco.MjContact, 'dist'),
      ('MjStatistic', mujoco.MjStatistic, 'extent'),
      ('MjLROpt', mujoco.MjLROpt, 'maxforce'),
      ('MjvPerturb', mujoco.MjvPerturb, 'select'),
      ('MjvCamera', mujoco.MjvCamera, 'fixedcamid'),
  ])
  def test_mj_struct_equality(self, cls, attr):
    struct = cls()
    struct2 = cls()
    setattr(struct, attr, 1)
    self.assertNotEqual(struct, struct2)
    setattr(struct2, attr, 1)
    self.assertEqual(struct, struct2)

    self.assertNotEqual(struct, 3)
    self.assertNotEqual(struct, None)

    # mutable structs shouldn't declare __hash__
    with self.assertRaises(TypeError):
      hash(struct)

  def test_mj_struct_equality_array(self):
    contact1 = mujoco.MjContact()
    contact2 = mujoco.MjContact()
    contact1.H[3] = 1
    self.assertNotEqual(contact1, contact2)
    contact2.H[3] = 1
    self.assertEqual(contact1, contact2)

  @parameterized.named_parameters([
      ('MjOption', mujoco.MjOption, 'tolerance'),
      ('MjWarningStat', mujoco.MjWarningStat, 'number'),
      ('MjTimerStat', mujoco.MjTimerStat, 'number'),
      ('MjSolverStat', mujoco.MjSolverStat, 'neval'),
      ('MjContact', mujoco.MjContact, 'dist'),
      ('MjStatistic', mujoco.MjStatistic, 'extent'),
      ('MjLROpt', mujoco.MjLROpt, 'maxforce'),
      ('MjvPerturb', mujoco.MjvPerturb, 'select'),
      ('MjvCamera', mujoco.MjvCamera, 'fixedcamid'),
  ])
  def test_mj_struct_repr(self, cls, attr):
    struct = cls()
    setattr(struct, attr, 1)
    representation = repr(struct)
    self.assertStartsWith(representation, f'<{cls.__name__}')
    self.assertIn(f'{attr}: 1', representation)
    self.assertEqual(str(struct), repr(struct))

  def test_mj_struct_repr_for_subclass(self):
    class MjWarningStatSubclass(mujoco.MjWarningStat):
      # ptr attribute could cause an infinite recursion, if the repr
      # implementation simply looked at all attributes.
      @property
      def ptr(self):
        return self

    # repr should include name of subclass.
    expected_repr = """<MjWarningStatSubclass
  lastinfo: 0
  number: 0
>"""

    self.assertEqual(repr(MjWarningStatSubclass()), expected_repr)
  def test_mju_rotVecQuat(self):  # pylint: disable=invalid-name
    vec = [1, 0, 0]
    quat = [np.cos(np.pi/8), 0, 0, np.sin(np.pi/8)]
    expected = np.array([1, 1, 0]) / np.sqrt(2)

    # Check that the output argument works, and that the binding returns None.
    res = np.empty(3, np.float64)
    self.assertIsNone(mujoco.mju_rotVecQuat(res, vec, quat))
    np.testing.assert_allclose(res, expected)

    # Check that the function can be called via keyword arguments.
    mujoco.mju_rotVecQuat(vec=vec, quat=quat, res=res)
    np.testing.assert_allclose(res, expected)

    # Check that the res argument must have the right size.
    with self.assertRaises(TypeError):
      mujoco.mju_rotVecQuat(np.empty(4, np.float64), vec, quat)

    # Check that the vec argument must have the right size.
    with self.assertRaises(TypeError):
      mujoco.mju_rotVecQuat(res, [1, 2, 3, 4], quat)

    # Check that the quat argument must have the right size.
    with self.assertRaises(TypeError):
      mujoco.mju_rotVecQuat(res, vec, [1, 2, 3])

    # Check that the output argument must have the correct dtype.
    with self.assertRaises(TypeError):
      mujoco.mju_rotVecQuat(vec, quat, res=np.empty(3, int))

  def test_mj_jacSite(self):  # pylint: disable=invalid-name
    mujoco.mj_forward(self.model, self.data)
    site_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, 'mysite')

    # Call mj_jacSite with only jacp.
    jacp = np.empty((3, 10), np.float64)
    mujoco.mj_jacSite(self.model, self.data, jacp, None, site_id)

    expected_jacp = np.array(
        [[0, 0, 0, 0, 0, 0, -1, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]])
    np.testing.assert_array_equal(jacp, expected_jacp)

    # Call mj_jacSite with only jacr.
    jacr = np.empty((3, 10), np.float64)
    mujoco.mj_jacSite(self.model, self.data, None, jacr, site_id)

    expected_jacr = np.array(
        [[0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
         [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]])
    np.testing.assert_array_equal(jacr, expected_jacr)

    # Call mj_jacSite with both jacp and jacr.
    jacp[:] = 0
    jacr[:] = 0
    mujoco.mj_jacSite(self.model, self.data, jacp, jacr, site_id)
    np.testing.assert_array_equal(jacp, expected_jacp)
    np.testing.assert_array_equal(jacr, expected_jacr)

    # Check that the jacp argument must have the right size.
    with self.assertRaises(TypeError):
      mujoco.mj_jacSite(
          self.model, self.data, np.empty((3, 6), jacp.dtype), None, site_id)

    # Check that the jacr argument must have the right size.
    with self.assertRaises(TypeError):
      mujoco.mj_jacSite(
          self.model, self.data, None, np.empty((4, 7), jacr.dtype), site_id)

    # Check that the jacp argument must have the right dtype.
    with self.assertRaises(TypeError):
      mujoco.mj_jacSite(
          self.model, self.data, np.empty(jacp.shape, int), None, site_id)

    # Check that the jacp argument must have the right dtype.
    with self.assertRaises(TypeError):
      mujoco.mj_jacSite(
          self.model, self.data, None, np.empty(jacr.shape, int), site_id)

  def test_docstrings(self):  # pylint: disable=invalid-name
    self.assertEqual(
        mujoco.mj_versionString.__doc__,
        """mj_versionString() -> str

Return the current version of MuJoCo as a null-terminated string.
""")
    self.assertEqual(
        mujoco.mj_Euler.__doc__,
        """mj_Euler(m: mujoco._structs.MjModel, d: mujoco._structs.MjData) -> None

Euler integrator, semi-implicit in velocity.
""")

  def test_int_constant(self):
    self.assertEqual(mujoco.mjMAXVFSNAME, 1000)

  def test_float_constant(self):
    self.assertEqual(mujoco.mjMAXVAL, 1e10)

  def test_string_constants(self):
    self.assertLen(mujoco.mjDISABLESTRING, mujoco.mjtDisableBit.mjNDISABLE)
    self.assertLen(mujoco.mjENABLESTRING, mujoco.mjtEnableBit.mjNENABLE)
    self.assertLen(mujoco.mjTIMERSTRING, mujoco.mjtTimer.mjNTIMER)
    self.assertLen(mujoco.mjLABELSTRING, mujoco.mjtLabel.mjNLABEL)
    self.assertLen(mujoco.mjFRAMESTRING, mujoco.mjtFrame.mjNFRAME)
    self.assertLen(mujoco.mjVISSTRING, mujoco.mjtVisFlag.mjNVISFLAG)
    self.assertLen(mujoco.mjRNDSTRING, mujoco.mjtRndFlag.mjNRNDFLAG)
    self.assertEqual(mujoco.mjDISABLESTRING[11], 'Refsafe')
    self.assertEqual(mujoco.mjVISSTRING[mujoco.mjtVisFlag.mjVIS_INERTIA],
                     ('&Inertia', '0', 'I'))

  def test_enum_values(self):
    self.assertEqual(mujoco.mjtJoint.mjJNT_FREE, 0)
    self.assertEqual(mujoco.mjtJoint.mjJNT_BALL, 1)
    self.assertEqual(mujoco.mjtJoint.mjJNT_SLIDE, 2)
    self.assertEqual(mujoco.mjtJoint.mjJNT_HINGE, 3)
    self.assertEqual(mujoco.mjtEnableBit.mjENBL_OVERRIDE, 1<<0)
    self.assertEqual(mujoco.mjtEnableBit.mjENBL_ENERGY, 1<<1)
    self.assertEqual(mujoco.mjtEnableBit.mjENBL_FWDINV, 1<<2)
    self.assertEqual(mujoco.mjtEnableBit.mjENBL_SENSORNOISE, 1<<3)
    self.assertEqual(mujoco.mjtEnableBit.mjNENABLE, 4)
    self.assertEqual(mujoco.mjtGeom.mjGEOM_PLANE, 0)
    self.assertEqual(mujoco.mjtGeom.mjGEOM_HFIELD, 1)
    self.assertEqual(mujoco.mjtGeom.mjGEOM_SPHERE, 2)
    self.assertEqual(mujoco.mjtGeom.mjGEOM_ARROW, 100)
    self.assertEqual(mujoco.mjtGeom.mjGEOM_ARROW1, 101)
    self.assertEqual(mujoco.mjtGeom.mjGEOM_ARROW2, 102)
    self.assertEqual(mujoco.mjtGeom.mjGEOM_NONE, 1001)

  def test_enum_from_int(self):
    self.assertEqual(mujoco.mjtJoint.mjJNT_FREE, mujoco.mjtJoint(0))
    self.assertEqual(mujoco.mjtGeom.mjGEOM_ARROW, mujoco.mjtGeom(value=100))
    # mjENABLE_FWDINV and mjNENABLE have the same int value. Default to the
    # first defined one.
    self.assertEqual(
        mujoco.mjtEnableBit.mjENBL_FWDINV,
        mujoco.mjtEnableBit(mujoco.mjtEnableBit.mjNENABLE.value))
    with self.assertRaises(ValueError):
      mujoco.mjtJoint(1000)
    with self.assertRaises(ValueError):
      mujoco.mjtJoint(-1)

  def test_can_raise_error(self):
    self.data.pstack = self.data.nstack
    with self.assertRaisesWithLiteralMatch(mujoco.FatalError, 'Stack overflow'):
      mujoco.mj_forward(self.model, self.data)

  def test_mjcb_time(self):

    class CallCounter:

      def __init__(self):
        self.count = 0

      def __call__(self):
        self.count += 1
        return self.count - 1

    call_counter = CallCounter()
    with temporary_callback(mujoco.set_mjcb_time, call_counter):
      self.assertIs(mujoco.get_mjcb_time(), call_counter)

      # Check that the callback setter and getter aren't callin g the function.
      self.assertEqual(call_counter.count, 0)

      mujoco.mj_forward(self.model, self.data)
      self.assertGreater(call_counter.count, 0)

    self.assertIsNone(mujoco.get_mjcb_time())

  def test_mjcb_time_exception(self):

    class TestError(RuntimeError):
      pass

    def raises_exception():
      raise TestError('string', (1, 2, 3), {'a': 1, 'b': 2})

    with temporary_callback(mujoco.set_mjcb_time, raises_exception):
      with self.assertRaises(TestError) as e:
        mujoco.mj_forward(self.model, self.data)
      self.assertEqual(
          e.exception.args, ('string', (1, 2, 3), {'a': 1, 'b': 2}))

    # Should not raise now that we've cleared the callback.
    mujoco.mj_forward(self.model, self.data)

  def test_mjcb_time_wrong_return_type(self):
    with temporary_callback(mujoco.set_mjcb_time, lambda: 'string'):
      with self.assertRaisesWithLiteralMatch(
          TypeError, 'mjcb_time callback did not return a number'):
        mujoco.mj_forward(self.model, self.data)

  def test_mjcb_time_not_callable(self):
    with self.assertRaisesWithLiteralMatch(
        TypeError, 'callback is not an Optional[Callable]'):
      mujoco.set_mjcb_time(1)

  def test_mjcb_sensor(self):

    class SensorCallback:

      def __init__(self, test, expected_model, expected_data):
        self.test = test
        self.expected_model = expected_model
        self.expected_data = expected_data
        self.count = 0

      def __call__(self, m, d, stage):
        self.test.assertIs(m, self.expected_model)
        self.test.assertIs(d, self.expected_data)
        self.test.assertEqual(stage, mujoco.mjtStage.mjSTAGE_VEL)
        d.sensordata[0] = 17
        self.count += 1

    model_with_sensor = mujoco.MjModel.from_xml_string(TEST_XML_SENSOR)
    data_with_sensor = mujoco.MjData(model_with_sensor)
    sensor_callback = SensorCallback(self, model_with_sensor, data_with_sensor)
    self.assertEqual(sensor_callback.count, 0)

    with temporary_callback(mujoco.set_mjcb_sensor, sensor_callback):
      mujoco.mj_forward(model_with_sensor, data_with_sensor)

    self.assertEqual(sensor_callback.count, 1)
    self.assertEqual(data_with_sensor.sensordata[0], 17)

  def test_can_initialize_mjv_structs(self):
    self.assertIsInstance(mujoco.MjvScene(), mujoco.MjvScene)
    self.assertIsInstance(mujoco.MjvCamera(), mujoco.MjvCamera)
    self.assertIsInstance(mujoco.MjvGLCamera(), mujoco.MjvGLCamera)
    self.assertIsInstance(mujoco.MjvGeom(), mujoco.MjvGeom)
    self.assertIsInstance(mujoco.MjvLight(), mujoco.MjvLight)
    self.assertIsInstance(mujoco.MjvOption(), mujoco.MjvOption)
    self.assertIsInstance(mujoco.MjvScene(), mujoco.MjvScene)
    self.assertIsInstance(mujoco.MjvScene(self.model, 100), mujoco.MjvScene)
    self.assertIsInstance(mujoco.MjvFigure(), mujoco.MjvFigure)

  def test_mjv_camera(self):
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_TRACKING
    # IDs should be integers
    camera.fixedcamid = 2**31 - 1
    self.assertEqual(camera.fixedcamid, 2**31 - 1)
    with self.assertRaises(TypeError):
      camera.fixedcamid = 0.5

  def test_mjv_scene(self):
    scene = mujoco.MjvScene(model=self.model, maxgeom=100)
    # scene.geoms is a fixed-length tuple of length maxgeom.
    self.assertEqual(scene.ngeom, 0)
    self.assertEqual(scene.maxgeom, 100)
    self.assertLen(scene.geoms, scene.maxgeom)
    # When the scene is updated, geoms are added to the scene
    # (ngeom is incremented)
    mujoco.mj_forward(self.model, self.data)
    mujoco.mjv_updateScene(self.model, self.data, mujoco.MjvOption(),
                           None, mujoco.MjvCamera(),
                           mujoco.mjtCatBit.mjCAT_ALL, scene)
    self.assertGreater(scene.ngeom, 0)

  def test_mjv_scene_without_model(self):
    scene = mujoco.MjvScene()
    self.assertEqual(scene.scale, 1.0)
    self.assertEqual(scene.maxgeom, 0)

  def test_mj_ray(self):
    # mj_ray has tricky argument types
    geomid = np.zeros(1, np.int32)
    mujoco.mj_ray(self.model, self.data, [0, 0, 0], [0, 0, 1], None, 0, 0,
                  geomid)
    mujoco.mj_ray(self.model, self.data, [0, 0, 0], [0, 0, 1],
                  [0, 0, 0, 0, 0, 0], 0, 0, geomid)
    # Check that named arguments work
    mujoco.mj_ray(
        m=self.model,
        d=self.data,
        pnt=[0, 0, 0],
        vec=[0, 0, 1],
        geomgroup=None,
        flg_static=0,
        bodyexclude=0,
        geomid=geomid)

  @parameterized.product(flg_html=(False, True), flg_pad=(False, True))
  def test_mj_printSchema(self, flg_html, flg_pad):  # pylint: disable=invalid-name
    # Make sure that mj_printSchema doesn't raise an exception
    # (e.g. because the internal output buffer is too small)
    self.assertIn('mujoco', mujoco.mj_printSchema(flg_html, flg_pad))

  def test_pickle_mjdata(self):
    mujoco.mj_step(self.model, self.data)
    data2 = pickle.loads(pickle.dumps(self.data))
    attr_to_compare = (
        'time', 'qpos', 'qvel', 'qacc', 'xpos', 'mocap_pos',
        'warning', 'energy'
    )
    self._assert_attributes_equal(data2, self.data, attr_to_compare)
    for _ in range(10):
      mujoco.mj_step(self.model, self.data)
      mujoco.mj_step(self.model, data2)
    self._assert_attributes_equal(data2, self.data, attr_to_compare)

  def test_pickle_mjmodel(self):
    model2 = pickle.loads(pickle.dumps(self.model))
    attr_to_compare = (
        'nq', 'nmat', 'body_pos', 'names',
    )
    self._assert_attributes_equal(model2, self.model, attr_to_compare)

  def _assert_attributes_equal(self, actual_obj, expected_obj, attr_to_compare):
    for name in attr_to_compare:
      actual_value = getattr(actual_obj, name)
      expected_value = getattr(expected_obj, name)
      try:
        if isinstance(expected_value, np.ndarray):
          np.testing.assert_array_equal(actual_value, expected_value)
        else:
          self.assertEqual(actual_value, expected_value)
      except AssertionError as e:
        self.fail("Attribute '{}' differs from expected value: {}".format(
            name, str(e)))

if __name__ == '__main__':
  absltest.main()