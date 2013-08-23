# =============================================================================
#
# EZID :: datacite_xml.py
#
# Allows processing a form with form elements named with simple XPATH
# expressions and creates an XML document for attaching Datacite XML
# metadata.
#
# Author:
#   Scott Fisher <sfisher@ucop.edu>
#
# License:
#   Copyright (c) 2013, Regents of the University of California
#   http://creativecommons.org/licenses/BSD/
#
# -----------------------------------------------------------------------------

from lxml import etree
import re
import copy

# this section generates the XML document based on form with XPATH expressions
def generate_xml(param_items):
  """This generates and returns a limited datacite XML document from form items.
  Pass in something like request.POST, for example.  Required elements are
  at least one creator, title, publisher and publicationYear"""
  r = etree.fromstring(u'<resource xmlns="http://datacite.org/schema/kernel-3"' + \
                       u' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' + \
                       u' xsi:schemaLocation="http://datacite.org/schema/kernel-3' + \
                       u' http://schema.datacite.org/meta/kernel-3/metadata.xsd"/>')
  
  id_type = _id_type(param_items[u'shoulder'])

  items = [x for x in param_items.items() if x[0].startswith(u"/resource") ]
  RESOURCE_ORDER = [u"/resource/" + x for x in [u'creators', u'titles', u'publisher', u'publicationYear', u'subjects', 
                    u'contributors', u'dates', u'resourceType', u'alternateIdentifiers',
                    u'relatedIdentifiers', u'rightsList', u'descriptions', u'geoLocations'] ]
  items = sorted(items, key=lambda i: i[0]) #sort by element name of params
  #sort by ordinal(s) in string, this may not work all complex cases but should work for datacite
  items = sorted(items, key=lambda i: _sort_get_ordinal(i[0])) #sort by ordinal
  items = sorted(items, key=lambda i: RESOURCE_ORDER.
                 index(re.search('^/resource/[a-zA-Z0-9\[\]]+', i[0]).group())) #sort in preferred order of sections

  _create_xml_element(r, u'/resource/identifier/@identifierType', id_type) #must create empty element and specify type to mint
  
  for k, v in items:
    if v != u'':
      _create_xml_element(r, k, v)
    
  return u"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + \
    etree.tostring(r, encoding=unicode, method="xml", pretty_print=True)

def _create_xml_element(root_el, path, value):
  """ creates xml element """
  split_path = path.split(u"/")[1:]
  if split_path[0] == _remove_ns(root_el.tag):
    split_path = split_path[1:]
  _xml_create(root_el, split_path, value)
  
def _xml_create(base_el, path_arr, value):
  #create or check element here
  tag = path_arr[0]
  simple_tag = _remove_at(_remove_ordinal(tag))
  children = _children_w_tag(base_el, simple_tag)
  if _is_attribute(tag):
    #set an attribute
    if len(path_arr) > 1:
      #this shouldn't happen
      return
    else:
      base_el.set(simple_tag, value)
  else:
    if _has_ordinal(tag):
      ord = _get_ordinal(tag) - 1 #must subtract one because form ordinals start at 1, not 0
    else:
      ord = 0  #no ordinal, then it's effectively an ordinal of the first [0]
    if ord > len(children) - 1:
      child = etree.Element(simple_tag)
      base_el.append(child)
    else:
      child = children[ord]
    if len(path_arr) == 1:
      child.text = value  #leaf node, so set value
    else:
      _xml_create(child, path_arr[1:], value) #not leaf node, so recurse for more path

def _remove_ns(str):
  """ removes the horrifying namespace uri from string so can compare easily"""
  return re.sub(r'^{[^}]+}', u'', str)

def _children_w_tag(base, tag):
  return [ child for child in base.iter(tag) ]
  #was [child for child in base if _remove_ns(child.tag) == tag ]

def _remove_ordinal(str):
  """removes the ordinal like [1] from path element"""
  return re.sub(r'\[[0-9]+\]$', u'', str)

def _has_ordinal(str):
  """sees if it has an ordinal like [1] at end of element"""
  return str.endswith(u"]")

def _get_ordinal(str):
  """gets the ordinal at end of element string like [1] and returns an integer"""
  return int(re.search('\[([0-9]+)\]$', str).group(1))

def _is_attribute(str):
  """sees if this element string is an attribute"""
  return str.startswith(u"@")

def _remove_at(str):
  """removes an @ sign at beginning of string if it exists"""
  return re.sub(r'^@', u'', str)

def _sort_get_ordinal(str):
  """gets the ordinal(s) in the element string, if it doesn't have any return [0]"""
  m = re.compile('\[([0-9]+)\]')
  if m.search(str) == None:
    return [0]
  else:
    return [int(x) for x in m.findall(str)]
  
def _id_type(str):
  m = re.compile("^[a-z]+")
  if m.search(str) == None:
    return u''
  else:
    return m.findall(str)[0].upper()
  
def validate_document(xml_doc, xsd_path, err_msgs):
  """Validates the document agains the XSD and adds
  error messages to the err_msgs array if things go wrong"""
  cleansed_xml = xml_doc.replace('encoding="UTF-8"', '', 1)  
  xsd_doc = etree.parse(xsd_path)
  xsd = etree.XMLSchema(xsd_doc)
  parser = etree.XMLParser(ns_clean=True, recover=True)
  xml = etree.fromstring(cleansed_xml, parser)
  
  # must add something like <identifier identifierType="DOI">10.5072/FK25Q56C6</identifier>
  # because it will not validate until it's present, even though we haven't minted
  # an identifier yet, but want to validate as though we had
  el = xml.find('{http://datacite.org/schema/kernel-3}identifier')
  el.attrib['identifierType'] = 'DOI'
  el.text = '10.5072/FK25Q56C6'
  
  if not xsd.validate(xml):
    #err_msgs.append("XML validation errors occurred for the values you entered:")
    simple_errors = [re.sub("\\{http://[^ ]+?\\}", '', x.message) for x in xsd.error_log] #removes namespace crap
    err_msgs.extend(_translate_errors(simple_errors))
    return False
  return True

def _translate_errors(err_in):
  """translates the errors returned by lxml and libxml2 into more
  readable errors by users.  If no translation, then passes it through"""
  errs_copy = copy.copy(err_in)
  errs_out = []
  exact_errs = {"Element 'contributor': The attribute 'contributorType' is required but missing.":
                  "Contributor Type is required if you fill in contributor information.",
                "Element 'description': The attribute 'descriptionType' is required but missing.":
                  "If descriptive information is present in the Abstract section, a type must be selected.",
                "Element 'contributor': Missing child element(s). Expected is ( contributorName ).":
                  "Contributor Name is required if you fill in contributor information.",
                "Element 'nameIdentifier': This element is not expected. Expected is ( contributorName ).":
                  "Contributor Name is required if you fill in contributor information.",
                "Element 'date': The attribute 'dateType' is required but missing.":
                  "Date Type is required if you fill in a Date.",
                "Element 'alternateIdentifier': The attribute 'alternateIdentifierType' is required but missing.":
                  "The Alternate Identifier Type is required if you fill in an Alternate Identifier.",
                "Element 'relatedIdentifier': The attribute 'relatedIdentifierType' is required but missing.":
                  "The Related Identifier Type is required if you fill in a Related Identifier.",
                "Element 'relatedIdentifier': The attribute 'relationType' is required but missing.":
                  "You Related Identifier Relation Type is required if you fill in a Related Identifier.",
                "Element 'geoLocationPoint': [facet 'minLength'] The value has a length of '1'; this underruns the allowed minimum length of '2'.":
                  "Geolocation points must be made up of two numbers separated by a space."}
  
  regex_errs = {"^Element\\ 'geoLocationPoint':\\ '.+?'\\ is\\ not\\ a\\ valid\\ value\\ of\\ the\\ atomic\\ type\\ 'xs:double'\\.$":
                  'A Geolocation Point must use only decimal numbers for coordinates.',
                "^Element\\ 'geoLocationPoint':\\ '.+?'\\ is\\ not\\ a\\ valid\\ value\\ of\\ the\\ list\\ type\\ 'point'\\.$":
                  '',
                "^Element\\ 'geoLocationPoint':\\ \\[facet\\ 'maxLength'\\]\\ The\\ value\\ has\\ a\\ length\\ of\\ '.+?';\\ this\\ exceeds\\ the\\ allowed\\ maximum\\ length\\ of\\ '2'\\.$":
                  'Geolocation points must be made up of two numbers separated by a space.'
                }
  
  
  # add translation of any exact errors
  for key, value in exact_errs.iteritems():
    if key in errs_copy:
      errs_out.append(value)
      errs_copy.remove(key)
      
  # add translation of any regex matches for errors
  temp_trans = {}
  for err in errs_copy:
    for key, value in regex_errs.iteritems():
      a = re.compile(key)
      if a.match(err):
        temp_trans[err] = value
        break
  
  for key, value in temp_trans.iteritems():
    errs_out.append(value)
    errs_copy.remove(key)
 
  # add any untranslated errors
  for err in errs_copy:
    errs_out.append(err)
  return [x for x in errs_out if x]
