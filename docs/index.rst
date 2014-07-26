******
tl;dr
******

To quickly get started building .pex (PEX) files, go straight to :ref:`buildingpex`

pex
===

pex contains the Python packaging and distribution libraries originally available through the 
`twitter commons <https://github.com/twitter/commons>`_ but since split out into a separate project.
The most notable components of the ``pex`` library are the .pex (Python EXecutable) format and the
associated ``pex`` tool which provide a general purpose Python environment virtualization
solution similar in spirit to `virtualenv <http://virtualenv.org>`_.  PEX files have been used by Twitter
to deploy Python applications to production since 2011.

To learn more about what the .pex format is and why it could be useful for
you, see :ref:`whatispex`  For the impatient, there is also a lightning
talk published by Twitter University: `WTF is PEX?
<http://www.youtube.com/watch?v=NmpnGhRwsu0>`_.


Guide:

.. toctree::
   :maxdepth: 2

   whatispex
   buildingpex
   api/index
