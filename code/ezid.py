# =============================================================================
#
# EZID :: ezid.py
#
# Main functionality.
#
# All identifier metadata is stored in a single "bind" noid instance.
# Metadata for an ARK identifier (e.g., ark:/13030/foo) is keyed by
# the canonical form of that identifier (see util.validateArk);
# metadata for a non-ARK identifier (e.g., doi:10.5060/FOO) is keyed
# by the identifier's shadow ARK (e.g., ark:/b5060/foo).  The
# supported non-ARK identifiers include DOIs and URNs.
#
# The shadow ARK for a non-ARK identifier is computable by a simple
# mapping (see util.doi2shadow, util.urnUuid2shadow, etc.); the
# reverse mapping is not simple and requires a lookup.
#
# Shadow ARKs provide a technical means of storing metadata for
# non-ARK identifiers, but they're also identifiers in their own
# right: they're advertised to users and they independently resolve.
# But while a non-ARK identifier and its shadow ARK may have different
# target URLs, they otherwise share all metadata (owner, creation
# time, etc.), and so they should be considered closely-related
# identifiers.
#
# Identifier metadata is structured as element (name, value) pairs.
# Element names are not repeatable.  Names are arbitrary and
# uncontrolled, but those beginning with an underscore are reserved
# for internal use by EZID and other services.  Reserved element names
# have two forms: a short form used for storage and a longer, more
# readable form used in communicating with clients.  In the following
# table, it may appear that different elements have the same long form
# name, but the context always makes it clear which is being returned.
#
# stored | transmitted |
# label  | label       | meaning
# -------+-------------+----------------------------------------------
# _o     | _owner      | The identifier's owner.  The owner is stored
#        |             | as a persistent identifier (e.g.,
#        |             | "ark:/13030/foo") but returned as a local
#        |             | name (e.g., "ryan").  For a shadow ARK,
#        |             | applies to both the shadow ARK and shadowed
#        |             | identifier.
# _g     | _ownergroup | The identifier's owner's group.  The group is
#        |             | stored as a persistent identifier (e.g.,
#        |             | "ark:/13030/bar") but returned as a local
#        |             | name (e.g., "dryad").  For a shadow ARK,
#        |             | applies to both the shadow ARK and shadowed
#        |             | identifier.
# _co    | _coowners   | The identifier's co-owners expressed as a
#        |             | list of persistent identifiers separated by
#        |             | semicolons (e.g., "ark:/13030/foo ;
#        |             | ark:/13030/bar") but returned as a list of
#        |             | local names (e.g., "peter ; paul").  For a
#        |             | shadow ARK, applies to both the shadow ARK
#        |             | and shadowed identifier.  Optional.
# _c     | _created    | The time the identifier was created expressed
#        |             | as a Unix timestamp, e.g., "1280889190".  For
#        |             | a shadow ARK, applies to both the shadow ARK
#        |             | and shadowed identifier.
# _u     | _updated    | The time the identifier was last modified
#        |             | expressed as a Unix timestamp, e.g.,
#        |             | "1280889190".  For a shadow ARK, applies to
#        |             | the ARK only, not the shadowed identifier.
# _t     | _target     | The identifier's target URL, e.g.,
#        |             | "http://foo.com/bar".  For a shadow ARK,
#        |             | applies to the ARK only, not the shadowed
#        |             | identifier.
# _s     | _shadows    | Shadow ARKs only.  The shadowed identifier,
#        |             | e.g., "doi:10.5060/foo".
# _su    | _updated    | Shadow ARKs only.  The time the shadowed
#        |             | identifier was last modified expressed as a
#        |             | Unix timestamp, e.g., "1280889190".
# _st    | _target     | Shadow ARKs only.  The shadowed identifier's
#        |             | target URL, e.g., "http://foo.com/bar".
#        | _shadowedby | Shadowed identifiers only.  The identifier's
#        |             | shadow ARK, e.g., "ark:/b5060/foo".  This is
#        |             | computed, not stored.
# _p     | _profile    | The identifier's preferred metadata profile,
#        |             | e.g., "erc".  See module metadata for more
#        |             | information on profiles.  A profile is not
#        |             | required, nor does the presence of a profile
#        |             | place any requirements on what metadata
#        |             | elements must be present or restrict what
#        |             | metadata elements can be present.  By
#        |             | convention, the element names of a profile
#        |             | are prefixed with the profile name, e.g.,
#        |             | "erc.who".
# _is    | _status     | Identifier status; either "reserved",
#        |             | "public", or "unavailable".  If
#        |             | "unavailable", a reason may follow separated
#        |             | by a pipe character, e.g., "unavailable |
#        |             | withdrawn by author".  Optional, but always
#        |             | returned; if no value is stored, "public" is
#        |             | implied and returned.
#
# Element names and values are first UTF-8 encoded, and then
# non-graphic ASCII characters and a few other reserved characters are
# percent-encoded; see util.encode{3,4} and util.decode.
#
# ARK identifiers that identify users and groups ("agent identifiers")
# are treated specially by EZID.  Such identifiers are identified by
# the presence of an _ezid_role metadata element, which may have the
# value "user" or "group".  Additional metadata elements cache
# information stored primarily in LDAP.  Agent identifiers are owned
# by the EZID administrator, and to protect user privacy, they may be
# viewed by the EZID administrator only.
#
# Author:
#   Greg Janee <gjanee@ucop.edu>
#
# License:
#   Copyright (c) 2010, Regents of the University of California
#   http://creativecommons.org/licenses/BSD/
#
# -----------------------------------------------------------------------------

import exceptions
import re
import threading
import time
import urllib
import uuid

import config
import datacite
import idmap
import log
import noid
import policy
import util

_bindNoid = None
_ezidUrl = None
_prefixes = None
_defaultDoiProfile = None
_defaultArkProfile = None
_defaultUrnUuidProfile = None
_adminUsername = None

def _loadConfig ():
  global _bindNoid, _ezidUrl, _prefixes, _defaultDoiProfile, _defaultArkProfile
  global _defaultUrnUuidProfile, _adminUsername
  _bindNoid = noid.Noid(config.config("DEFAULT.bind_noid"))
  _ezidUrl = config.config("DEFAULT.ezid_base_url")
  _prefixes = dict([config.config("prefix_%s.prefix" % k),
    noid.Noid(config.config("prefix_%s.minter" % k))]\
    for k in config.config("prefixes.keys").split(","))
  _defaultDoiProfile = config.config("DEFAULT.default_doi_profile")
  _defaultArkProfile = config.config("DEFAULT.default_ark_profile")
  _defaultUrnUuidProfile = config.config("DEFAULT.default_urn_uuid_profile")
  _adminUsername = config.config("ldap.admin_username")

_loadConfig()
config.addLoader(_loadConfig)

# Simple locking mechanism to ensure that, in a multi-threaded
# environment, no given identifier is operated on by two threads
# simultaneously.

_lockedIdentifiers = set()
_lock = threading.Condition()

def _acquireIdentifierLock (identifier):
  _lock.acquire()
  while identifier in _lockedIdentifiers: _lock.wait()
  _lockedIdentifiers.add(identifier)
  _lock.release()

def _releaseIdentifierLock (identifier):
  _lock.acquire()
  _lockedIdentifiers.remove(identifier)
  _lock.notifyAll()
  _lock.release()

def numIdentifiersLocked ():
  """
  Returns the number of identifiers currently locked (and thus being
  operated on).
  """
  return len(_lockedIdentifiers)

_labelMapping = {
  "_o": "_owner",
  "_g": "_ownergroup",
  "_co": "_coowners",
  "_c": "_created",
  "_u": "_updated",
  "_t": "_target",
  "_s": "_shadows",
  "_su": "_updated",
  "_st": "_target",
  "_p": "_profile",
  "_is": "_status"
}

def mintDoi (prefix, user, group, target=None):
  """
  Mints a DOI identifier having the given scheme-less prefix, e.g.,
  "10.5060/".  'user' and 'group' should each be authenticated (local
  name, persistent identifier) tuples, e.g., ("dryad",
  "ark:/13030/foo").  If an initial target URL is not supplied, the
  identifier is given a self-referential target URL.  The successful
  return is a string that includes the canonical, scheme-less form of
  the new identifier, followed by the new identifier's qualified
  shadow ARK, as in:

    success: 10.5060/FK35717N0H | ark:/b5060/fk35717n0h

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  qprefix = "doi:" + prefix
  if qprefix not in _prefixes:
    return "error: bad request - unrecognized DOI prefix"
  tid = uuid.uuid1()
  try:
    log.begin(tid, "mintDoi", prefix, user[0], user[1], group[0], group[1],
      target or "None")
    if not policy.authorizeCreate(user, group, qprefix):
      log.unauthorized(tid)
      return "error: unauthorized"
    if _prefixes[qprefix].server == "":
      log.badRequest(tid)
      return "error: bad request - no minter for namespace"
    shadowArk = _prefixes[qprefix].mintIdentifier()
    doi = util.shadow2doi(shadowArk)
    assert doi.startswith(prefix), "minted DOI does not match requested prefix"
    assert util.doi2shadow(doi) == shadowArk,\
      "minted DOI does not map back to minted shadow ARK"
  except Exception, e:
    log.error(tid, e)
    return "error: internal server error"
  else:
    log.success(tid, doi)
  return createDoi(doi, user, group, target)

def createDoi (doi, user, group, target=None):
  """
  Creates a DOI identifier having the given scheme-less name, e.g.,
  "10.5060/foo".  The identifier must not already exist.  'user' and
  'group' should each be authenticated (local name, persistent
  identifier) tuples, e.g., ("dryad", "ark:/13030/foo").  If an
  initial target URL is not supplied, the identifier is given a
  self-referential target URL.  The successful return is a string that
  includes the canonical, scheme-less form of the new identifier,
  followed by the new identifier's qualified shadow ARK, as in:

    success: 10.5060/FOO | ark:/b5060/foo

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  doi = util.validateDoi(doi)
  if not doi: return "error: bad request - invalid DOI identifier"
  qdoi = "doi:" + doi
  shadowArk = util.doi2shadow(doi)
  tid = uuid.uuid1()
  _acquireIdentifierLock(shadowArk)
  try:
    log.begin(tid, "createDoi", doi, user[0], user[1], group[0], group[1],
      target or "None")
    if not policy.authorizeCreate(user, group, qdoi):
      log.unauthorized(tid)
      return "error: unauthorized"
    if _bindNoid.identifierExists(shadowArk):
      log.badRequest(tid)
      return "error: bad request - identifier already exists"
    if not target: target = "%s/id/%s" % (_ezidUrl, urllib.quote(qdoi, ":/"))
    arkTarget = "%s/id/%s" % (_ezidUrl,
      urllib.quote("ark:/" + shadowArk, ":/"))
    datacite.registerIdentifier(doi, target)
    _bindNoid.holdIdentifier(shadowArk)
    t = str(int(time.time()))
    _bindNoid.setElements(shadowArk,
      { "_o": user[1],
        "_g": group[1],
        "_c": t,
        "_u": t,
        "_t": arkTarget,
        "_s": qdoi,
        "_su": t,
        "_st": target,
        "_p": _defaultDoiProfile })
  except Exception, e:
    log.error(tid, e)
    return "error: internal server error"
  else:
    log.success(tid)
    return "success: " + doi + " | ark:/" + shadowArk
  finally:
    _releaseIdentifierLock(shadowArk)

def mintArk (prefix, user, group, target=None):
  """
  Mints an ARK identifier having the given scheme-less prefix, e.g.,
  "13030/fk4".  'user' and 'group' should each be authenticated (local
  name, persistent identifier) tuples, e.g., ("dryad",
  "ark:/13030/foo").  If an initial target URL is not supplied, the
  identifier is given a self-referential target URL.  The successful
  return is a string that includes the canonical, scheme-less form of
  the new identifier, as in:

    success: 13030/fk45717n0h

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  qprefix = "ark:/" + prefix
  if qprefix not in _prefixes:
    return "error: bad request - unrecognized ARK prefix"
  tid = uuid.uuid1()
  try:
    log.begin(tid, "mintArk", prefix, user[0], user[1], group[0], group[1],
      target or "None")
    if not policy.authorizeCreate(user, group, qprefix):
      log.unauthorized(tid)
      return "error: unauthorized"
    if _prefixes[qprefix].server == "":
      log.badRequest(tid)
      return "error: bad request - no minter for namespace"
    ark = _prefixes[qprefix].mintIdentifier()
    assert ark.startswith(prefix), "minted ARK does not match requested prefix"
  except Exception, e:
    log.error(tid, e)
    return "error: internal server error"
  else:
    log.success(tid, ark)
  return createArk(ark, user, group, target)

def createArk (ark, user, group, target=None):
  """
  Creates an ARK identifier having the given scheme-less name, e.g.,
  "13030/bar".  The identifier must not already exist.  'user' and
  'group' should each be authenticated (local name, persistent
  identifier) tuples, e.g., ("dryad", "ark:/13030/foo").  If an
  initial target URL is not supplied, the identifier is given a
  self-referential target URL.  The successful return is a string that
  includes the canonical, scheme-less form of the new identifier, as
  in:

    success: 13030/bar

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  ark = util.validateArk(ark)
  if not ark: return "error: bad request - invalid ARK identifier"
  qark = "ark:/" + ark
  tid = uuid.uuid1()
  _acquireIdentifierLock(ark)
  try:
    log.begin(tid, "createArk", ark, user[0], user[1], group[0], group[1],
      target or "None")
    if not policy.authorizeCreate(user, group, qark):
      log.unauthorized(tid)
      return "error: unauthorized"
    if _bindNoid.identifierExists(ark):
      log.badRequest(tid)
      return "error: bad request - identifier already exists"
    _bindNoid.holdIdentifier(ark)
    if not target: target = "%s/id/%s" % (_ezidUrl, urllib.quote(qark, ":/"))
    t = str(int(time.time()))
    _bindNoid.setElements(ark,
      { "_o": user[1],
        "_g": group[1],
        "_c": t,
        "_u": t,
        "_t": target,
        "_p": _defaultArkProfile })
  except Exception, e:
    log.error(tid, e)
    return "error: internal server error"
  else:
    log.success(tid)
    return "success: " + ark
  finally:
    _releaseIdentifierLock(ark)

def mintUrnUuid (user, group, target=None):
  """
  Mints a UUID URN.  'user' and 'group' should each be authenticated
  (local name, persistent identifier) tuples, e.g., ("dryad",
  "ark:/13030/foo").  If an initial target URL is not supplied, the
  identifier is given a self-referential target URL.  The successful
  return is a string that includes the canonical, scheme-less form of
  the new identifier, followed by the new identifier's qualified
  shadow ARK, as in:

    success: f81d4fae-7dec-11d0-a765-00a0c91e6bf6 | ark:/97720/f81...

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  return createUrnUuid(uuid.uuid1().urn[9:], user, group, target)

def createUrnUuid (urn, user, group, target=None):
  """
  Creates a UUID URN identifier having the given scheme-less name,
  e.g., "f81d4fae-7dec-11d0-a765-00a0c91e6bf6".  The identifier must
  not already exist.  'user' and 'group' should each be authenticated
  (local name, persistent identifier) tuples, e.g., ("dryad",
  "ark:/13030/foo").  If an initial target URL is not supplied, the
  identifier is given a self-referential target URL.  The successful
  return is a string that includes the canonical, scheme-less form of
  the new identifier, followed by the new identifier's qualified
  shadow ARK, as in:

    success: f81d4fae-7dec-11d0-a765-00a0c91e6bf6 | ark:/97720/f81...

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  urn = util.validateUrnUuid(urn)
  if not urn: return "error: bad request - invalid UUID URN identifier"
  qurn = "urn:uuid:" + urn
  shadowArk = util.urnUuid2shadow(urn)
  tid = uuid.uuid1()
  _acquireIdentifierLock(shadowArk)
  try:
    log.begin(tid, "createUrnUuid", urn, user[0], user[1], group[0], group[1],
      target or "None")
    if not policy.authorizeCreate(user, group, qurn):
      log.unauthorized(tid)
      return "error: unauthorized"
    if _bindNoid.identifierExists(shadowArk):
      log.badRequest(tid)
      return "error: bad request - identifier already exists"
    if not target: target = "%s/id/%s" % (_ezidUrl, urllib.quote(qurn, ":/"))
    arkTarget = "%s/id/%s" % (_ezidUrl,
      urllib.quote("ark:/" + shadowArk, ":/"))
    _bindNoid.holdIdentifier(shadowArk)
    t = str(int(time.time()))
    _bindNoid.setElements(shadowArk,
      { "_o": user[1],
        "_g": group[1],
        "_c": t,
        "_u": t,
        "_t": arkTarget,
        "_s": qurn,
        "_su": t,
        "_st": target,
        "_p": _defaultUrnUuidProfile })
  except Exception, e:
    log.error(tid, e)
    return "error: internal server error"
  else:
    log.success(tid)
    return "success: " + urn + " | ark:/" + shadowArk
  finally:
    _releaseIdentifierLock(shadowArk)

def mintIdentifier (prefix, user, group, target=None):
  """
  Mints an identifier having the given qualified prefix, e.g.,
  "doi:10.5060/".  'user' and 'group' should each be authenticated
  (local name, persistent identifier) tuples, e.g., ("dryad",
  "ark:/13030/foo").  If an initial target URL is not supplied, the
  identifier is given a self-referential target URL.  The successful
  return is a string that includes the canonical, qualified form of
  the new identifier, as in:

    success: ark:/95060/fk35717n0h

  For non-ARK identifiers, the string also includes the qualified
  shadow ARK, as in:

    success: doi:10.5060/FK35717N0H | ark:/b5060/fk35717n0h

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  if prefix.startswith("doi:"):
    s = mintDoi(prefix[4:], user, group, target)
    if s.startswith("success: "):
      return "success: doi:" + s[9:]
    else:
      return s
  elif prefix.startswith("ark:/"):
    s = mintArk(prefix[5:], user, group, target)
    if s.startswith("success: "):
      return "success: ark:/" + s[9:]
    else:
      return s
  elif prefix == "urn:uuid:":
    s = mintUrnUuid(user, group, target)
    if s.startswith("success: "):
      return "success: urn:uuid:" + s[9:]
    else:
      return s
  else:
    return "error: bad request - unrecognized identifier scheme"

def createIdentifier (identifier, user, group, target=None):
  """
  Creates an identifier having the given qualified name, e.g.,
  "doi:10.5060/foo".  'user' and 'group' should each be authenticated
  (local name, persistent identifier) tuples, e.g., ("dryad",
  "ark:/13030/foo").  If an initial target URL is not supplied, the
  identifier is given a self-referential target URL.  The successful
  return is a string that includes the canonical, qualified form of
  the new identifier, as in:

    success: ark:/95060/foo

  For non-ARK identifiers, the string also includes the qualified
  shadow ARK, as in:

    success: doi:10.5060/FOO | ark:/b5060/foo

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  if identifier.startswith("doi:"):
    s = createDoi(identifier[4:], user, group, target)
    if s.startswith("success: "):
      return "success: doi:" + s[9:]
    else:
      return s
  elif identifier.startswith("ark:/"):
    s = createArk(identifier[5:], user, group, target)
    if s.startswith("success: "):
      return "success: ark:/" + s[9:]
    else:
      return s
  elif identifier.startswith("urn:uuid:"):
    s = createUrnUuid(identifier[9:], user, group, target)
    if s.startswith("success: "):
      return "success: urn:uuid:" + s[9:]
    else:
      return s
  else:
    return "error: bad request - unrecognized identifier scheme"

def getMetadata (identifier):
  """
  Returns all metadata for a given qualified identifier, e.g.,
  "doi:10.5060/foo".  The successful return is a pair (status,
  dictionary) where 'status' is a string that includes the canonical,
  qualified form of the identifier, as in:

    success: doi:10.5060/FOO

  and 'dictionary' contains element (name, value) pairs.  Unsuccessful
  returns include the strings:

    error: bad request - subreason...
    error: internal server error
  """
  if identifier.startswith("doi:"):
    doi = util.validateDoi(identifier[4:])
    if not doi: return "error: bad request - invalid DOI identifier"
    ark = util.doi2shadow(doi)
    nqidentifier = "doi:" + doi
  elif identifier.startswith("ark:/"):
    ark = util.validateArk(identifier[5:])
    if not ark: return "error: bad request - invalid ARK identifier"
    nqidentifier = "ark:/" + ark
  elif identifier.startswith("urn:uuid:"):
    urn = util.validateUrnUuid(identifier[9:])
    if not urn: return "error: bad request - invalid UUID URN identifier"
    ark = util.urnUuid2shadow(urn)
    nqidentifier = "urn:uuid:" + urn
  else:
    return "error: bad request - unrecognized identifier scheme"
  tid = uuid.uuid1()
  _acquireIdentifierLock(ark)
  try:
    log.begin(tid, "getMetadata", nqidentifier)
    d = _bindNoid.getElements(ark)
    if d is None:
      log.badRequest(tid)
      return "error: bad request - no such identifier"
    if nqidentifier.startswith("ark:/"):
      for k in filter(lambda k: k.startswith("_"), d):
        if k in ["_su", "_st"]:
          del d[k]
        elif k in _labelMapping:
          d[_labelMapping[k]] = d[k]
          del d[k]
    else:
      for k in filter(lambda k: k.startswith("_"), d):
        if k in ["_u", "_t", "_s"]:
          del d[k]
        elif k in _labelMapping:
          d[_labelMapping[k]] = d[k]
          del d[k]
      d["_shadowedby"] = "ark:/" + ark
    d["_owner"] = idmap.getAgent(d["_owner"])[0]
    d["_ownergroup"] = idmap.getAgent(d["_ownergroup"])[0]
    if "_coowners" in d:
      # Semicolons are not valid characters in ARK identifiers.
      d["_coowners"] = " ; ".join(idmap.getAgent(id.strip())[0]\
        for id in d["_coowners"].split(";") if len(id.strip()) > 0)
    if "_status" not in d: d["_status"] = "public"
    log.success(tid)
    return ("success: " + nqidentifier, d)
  except Exception, e:
    log.error(tid, e)
    return "error: internal server error"
  finally:
    _releaseIdentifierLock(ark)

def _oneline (s):
  return re.sub("\s", " ", s)

def setMetadata (identifier, user, group, metadata):
  """
  Sets metadata elements of a given qualified identifier, e.g.,
  "doi:10.5060/foo".  'user' and 'group' should each be authenticated
  (local name, persistent identifier) tuples, e.g., ("dryad",
  "ark:/13030/foo").  'metadata' should be a dictionary of element
  (name, value) pairs.  If an element being set already exists, it is
  overwritten, if not, it is created; existing elements not set are
  left unchanged.  Of the reserved metadata elements, only
  "_coowners", "_target", and "_profile" may be set (unless the user
  is the EZID administrator, in which case the other reserved metadata
  elements may be set using their stored forms).  The successful
  return is a string that includes the canonical, qualified form of
  the identifier, as in:

    success: doi:10.5060/FOO

  Unsuccessful returns include the strings:

    error: unauthorized
    error: bad request - subreason...
    error: internal server error
  """
  if identifier.startswith("doi:"):
    doi = util.validateDoi(identifier[4:])
    if not doi: return "error: bad request - invalid DOI identifier"
    ark = util.doi2shadow(doi)
    nqidentifier = "doi:" + doi
  elif identifier.startswith("ark:/"):
    ark = util.validateArk(identifier[5:])
    if not ark: return "error: bad request - invalid ARK identifier"
    nqidentifier = "ark:/" + ark
  elif identifier.startswith("urn:uuid:"):
    urn = util.validateUrnUuid(identifier[9:])
    if not urn: return "error: bad request - invalid UUID URN identifier"
    ark = util.urnUuid2shadow(urn)
    nqidentifier = "urn:uuid:" + urn
  else:
    return "error: bad request - unrecognized identifier scheme"
  if len(filter(lambda k: len(k) == 0, metadata)) > 0:
    return "error: bad request - empty element name"
  if user[0] != _adminUsername and len(filter(lambda k: k.startswith("_") and\
    k not in ["_coowners", "_target", "_profile"], metadata)) > 0:
    return "error: bad request - use of reserved metadata element name"
  # The only citation element we validate.  If more such cases arise,
  # a more general mechanism should be emplaced.  Note that the
  # validation check here precludes updating a DataCite Metadata
  # Scheme record via a shadow ARK (but individual DataCite elements
  # can still be updated).
  if "datacite" in metadata and metadata["datacite"].strip() != "":
    try:
      metadata["datacite"] = datacite.validateDcmsRecord(nqidentifier,
        metadata["datacite"])
    except AssertionError, e:
      return "error: bad request - element 'datacite': " + _oneline(str(e))
  tid = uuid.uuid1()
  _acquireIdentifierLock(ark)
  try:
    log.begin(tid, "setMetadata", nqidentifier, user[0], user[1], group[0],
      group[1], *[a for p in metadata.items() for a in p])
    m = _bindNoid.getElements(ark)
    if m is None:
      log.badRequest(tid)
      return "error: bad request - no such identifier"
    iUser = m["_o"]
    iGroup = m["_g"]
    if "_co" in m:
      # Semicolons are not valid characters in ARK identifiers.
      iCoOwners = [co.strip() for co in m["_co"].split(";")\
        if len(co.strip()) > 0]
    else:
      iCoOwners = []
    if not policy.authorizeUpdate(user, group, nqidentifier,
      (idmap.getAgent(iUser)[0], iUser), (idmap.getAgent(iGroup)[0], iGroup),
      [(idmap.getAgent(co)[0], co) for co in iCoOwners], metadata.keys()):
      log.unauthorized(tid)
      return "error: unauthorized"
    metadata = metadata.copy()
    coOwners = None
    if "_coowners" in metadata:
      coOwners = []
      for co in metadata["_coowners"].split(";"):
        co = co.strip()
        if co in ["", "anonymous", _adminUsername]: continue
        try:
          id = idmap.getUserId(co)
        except Exception, e:
          if type(e) is exceptions.AssertionError and\
            "unknown user" in e.message:
            log.badRequest(tid)
            return "error: bad request - no such user in co-owner list"
          else:
            raise
        if id != iUser and id not in coOwners: coOwners.append(id)
      del metadata["_coowners"]
    # If the user is not the owner of the identifier, add the user to
    # the identifier's co-owner list.
    if user[1] != iUser and user[0] != _adminUsername:
      if coOwners is None:
        if user[1] not in iCoOwners: coOwners = iCoOwners + [user[1]]
      else:
        if user[1] not in coOwners: coOwners.append(user[1])
    profile = None
    if "_profile" in metadata:
      profile = metadata["_profile"]
      del metadata["_profile"]
    if nqidentifier.startswith("doi:"):
      target = None
      if "_target" in metadata:
        target = metadata["_target"]
        del metadata["_target"]
        datacite.setTargetUrl(doi, target)
      if len(metadata) > 0:
        message = datacite.uploadMetadata(doi, m, metadata)
        if message is not None:
          log.badRequest(tid)
          return "error: bad request - element 'datacite': " +\
            _oneline(message)
      if target is not None: metadata["_st"] = target
      if "_su" not in metadata: metadata["_su"] = str(int(time.time()))
    elif nqidentifier.startswith("ark:/"):
      target = None
      if "_target" in metadata:
        target = metadata["_target"]
        del metadata["_target"]
      if "_s" in m and m["_s"].startswith("doi:") and len(metadata) > 0:
        message = datacite.uploadMetadata(m["_s"][4:], m, metadata)
        if message is not None:
          log.badRequest(tid)
          return "error: bad request - element 'datacite': " +\
            _oneline(message)
      if target is not None: metadata["_t"] = target
      if "_u" not in metadata: metadata["_u"] = str(int(time.time()))
    elif nqidentifier.startswith("urn:uuid:"):
      if "_target" in metadata:
        metadata["_st"] = metadata["_target"]
        del metadata["_target"]
      if "_su" not in metadata: metadata["_su"] = str(int(time.time()))
    else:
      assert False, "unhandled case"
    if coOwners is not None: metadata["_co"] = " ; ".join(coOwners)
    if profile is not None: metadata["_p"] = profile
    _bindNoid.setElements(ark, metadata)
  except Exception, e:
    log.error(tid, e)
    return "error: internal server error"
  else:
    log.success(tid)
    return "success: " + nqidentifier
  finally:
    _releaseIdentifierLock(ark)
