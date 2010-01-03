#  amee.py
#
# A simple Python interface to the AMEE API, designed to work on Google App Engine.
# Does not expose the entire API - just the bits that I personally need - though the
# AMEE.request method can be used to make arbitrary API calls, and it should be easy
# to extend if necessary.
#
# The dependencies on App Engine are:
#
#  - direct use of the urlfetch API (the urllib wrapper imposes unreasonably short timeouts),
#  - use of memcache to cache data item UIDs.
#
# I am very much up for replacing these with more general mechanisms if anyone wants to
# use this in a different environment.
# 
# Example usage:
# 
# a = amee.AMEE(username, password)
# 
# profile = a.create_profile()
# print "Created AMEE profile with UID %s" % (profile.uid,)
# 
# electricity = profile.create_item(
#   "/business/energy/electricity", {"country": "United Kingdom"},
#   {"energyPerTime": electricity_kwh_per_year}
# )
# 
# print "Electricity: %d kWh per year, resulting in %d kg of CO2" % (electricity_kwh_per_year, electricity.co2())
# 
# profile.delete()

#  -- Robin Houston, January 2010


import logging
import re
import urllib

from google.appengine.api import (memcache, urlfetch)
from django.utils import simplejson as json


DEFAULT_SERVER = 'https://stage.co2.dgen.net' # Use an encrypted transport by default
MEMCACHE_NAMESPACE = 'AMEE'

class Error(Exception):
  '''An AMEE-specific error, either from this module or from the API itself.'''

class APIError(Error):
  '''An error from the AMEE API'''

class AMEE(object):
  '''Represents the AMEE API.
  '''
  
  def __init__(self, username, password, server=DEFAULT_SERVER):
    self.username = username
    self.password = password
    self.server = server
    self.authtoken = None

  def get_authtoken(self):
    '''Get a new authentication token from AMEE (if the old one has expired,
    or we haven't got one yet).
    '''
    self.authtoken = None # Saves a wasted request later if the next line times out
    self.authtoken = self._make_request("/auth", "POST", {
      "username": self.username,
      "password": self.password,
    }).headers["authToken"]
    
    if not self.authtoken:
      raise APIError("Failed to authenticate with AMEE")
  
  def _make_request(self, path, method, payload, request_headers={}):
    if payload is not None and not isinstance(payload, basestring):
      payload = urllib.urlencode(payload)

    if re.match(r'https?://', path):
      uri = path
    else:
      if not path.startswith("/"):
        raise Error("Path '%s' does not start with /" % (path,))
      uri = self.server + path

    headers = {
      "Accept": "application/json",
      "AuthToken": self.authtoken,
      'Cache-Control' : 'max-age=0',
    }
    headers.update(request_headers)

    response = urlfetch.fetch(uri,
      method=method,
      payload=payload,
      follow_redirects=False,
      deadline=10,
      headers=headers
    )
    
    if response.status_code not in (200, 201, 401):
      raise APIError("Status code %d from %s to %s" % (response.status_code, method, path))

    return response

  def request(self, path, method="GET", payload=None, request_headers={}):
    '''Make a request to the AMEE API, and return the resulting data structure
    (parsed from the JSON response).
    '''
    if not self.authtoken:
      self.get_authtoken()

    response = self._make_request(path, method, payload, request_headers)

    if response.status_code == 401:
      # The authtoken must have expired
      logging.info("AMEE authentication token expired")
      self.get_authtoken()
      response = self._make_request(path, method, payload)
      if response.status_code == 401:
        raise APIError("AMEE rejected fresh authentication token")

    if response.status_code == 201:
      return response.headers["Location"]

    if not response.content:
      return None
    return json.loads(response.content)

  def create_profile(self):
    '''Create a new AMEE profile, and return it.
    '''
    return Profile(self, self.request("/profiles", "POST", {"profile": "true"})["profile"]["uid"])
  
  def profiles(self):
    '''Return a list of all profiles.'''
    return [ Profile(self, uid) for uid in self.profile_uids() ]
  
  def delete_profile(self, uid):
    '''Delete an AMEE profile, given the UID.
    '''
    self.request("/profiles/" + uid, "DELETE")
  
  def drill(self, path, choices, complete=False):
    '''Perform a data item drilldown.
    
    If all necessary choices are specified, returns the UID of the data item;
    otherwise, returns the next choice that needs to be made in the form of a dict
    with keys "name" and "choices". (The "choices" item is an array of permitted
    values.)
    
    If the "complete" argument is true, we raise an Error if the specified choices
    are incomplete. In this case the return value will always be the UID.
    
    Results are cached using memcache.
    '''
    choices_string = urllib.urlencode(choices)
    memcache_key = ";".join((self.server, path, choices_string, str(complete)))
    cached_result = memcache.get(memcache_key, namespace=MEMCACHE_NAMESPACE)
    if cached_result is not None:
      return cached_result
    
    result = self._drill(path, choices_string, complete)
    memcache.set(memcache_key, result, namespace=MEMCACHE_NAMESPACE)
    return result
  
  def _drill(self, path, choices_string, complete=False):
    '''Perform the drilldown directly, without caching
    '''
    r_choices = self.request("/data" + path + "/drill?" + choices_string)["choices"]
    
    # The "choices" item is an array of dicts with keys "name" and "value", which
    # appear always to be identical. We simplify this structure by replacing each
    # such choice with its name.
    r_choices["choices"] = [ choice["name"] for choice in r_choices["choices"] ]
    
    if r_choices["name"] == "uid":
      # We've finished drilling. This is it!
      if not r_choices["choices"]:
        raise Error("No choices returned. Did you specify an invalid value?")
      uid = r_choices["choices"][0]
      return uid
    
    if complete:
      raise Error("Incomplete drilldown, '%s' must be specified" % (r_choices["name"],))

    return r_choices

class Profile(object):
  def __init__(self, api, uid):
    self.api = api
    self.uid = uid

  def delete(self):
    '''Delete this profile.
    '''
    if self.uid is None:
      raise Error("Profile has already been deleted")
    self.api.delete_profile(self.uid)
    self.uid = None

  def create_item(self, path, choices, values):
    if self.uid is None:
      raise Error("Profile has been deleted")
    if not path.startswith("/"):
      raise Error("Path '%s' does not start with /" % (path,))
    data_item_uid = self.api.drill(path, choices, complete=True)
    
    params = {"dataItemUid": data_item_uid}
    params.update(values)
    item_uri = self.api.request("/profiles/%s%s" % (self.uid, path), "POST", params)

    return ProfileItem(api=self.api, uri=item_uri)
  
  def create_items(self, items, common_values={}):
    '''
    Create a number of profile items. The parameter 'items' should be an array
    (or other iterable) whose elements are 3-tuples (path, choices, values).
    
    In other words, p.create_items(items) is roughly equivalent to
    
      [ p.create_item(path, choices, values) for path, choices, values in items ]
    
    but more efficient, because it uses the AMEE batch update API. (One behaviour
    difference is that create_items is atomic, so that if one of the items fails then
    none of them will be created.)
    
    The return value is an array of ProfileItem objects, one for each item created.
    '''
    if self.uid is None:
      raise Error("Profile has been deleted")

    profile_items = []
    for path, choices, item_values in items:
      if not path.startswith("/"):
        raise Error("Path '%s' does not start with /" % (path,))

      h = {}
      h.update(common_values)
      h["dataItemUid"] = self.api.drill(path, choices, complete=True)
      h.update(item_values)
      profile_items.append(h)

    response = self.api.request("/profiles/" + self.uid, "POST", \
      json.dumps({"profileItems": profile_items}), {"Content-Type": "application/json"})
    
    return [ ProfileItem(api=self.api, uri=item["uri"]) for item in response["profileItems"] ]

class ProfileItem(object):
  def __init__(self, api, uri):
    self.api = api
    self.uri = uri
  
  def get(self):
    return self.api.request(self.uri, "GET")
  
  def co2(self):
    '''The amount of Carbon Dioxide represented by this profile item,
    in kilograms per year.
    '''
    amount = self.get()["profileItem"]["amount"]
    if amount["unit"] != "kg/year":
      raise Error("Profile item uses unit '%s' rather than kg/year" % (amount["unit"],))
    return amount["value"]
