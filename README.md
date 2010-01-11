Python-AMEE
=======

A simple Python interface to the AMEE API, designed to work on Google App Engine as
well as standard Python installs. Does not expose the entire API, though the
AMEE.request method can be used to make arbitrary API calls, and it should be easy
to extend if necessary.

## Dependencies

Either

* [Google App Engine](http://code.google.com/appengine/downloads.html#Google_App_Engine_SDK_for_Python)

or

* [Memcached](http://memcached.org/)
* [python-memcached](http://pypi.python.org/pypi/python-memcached/)
* Python 2.6+ or [Django](http://www.djangoproject.com/) (for json / simplejson)

## Getting started

Sign up for an [AMEE key](http://my.amee.com/signup). Create a project, and note your 
_Project Key Name_ and _Password_.

## Example usage

	a = amee.AMEE(username, password)

	profile = a.create_profile()
	print "Created AMEE profile with UID %s" % (profile.uid,)

	electricity_kwh_per_year = 1000

	electricity = profile.create_item(
  		"/business/energy/electricity", {"country": "United Kingdom"},
  		{"energyPerTime": electricity_kwh_per_year}
	)

	print "Electricity: %d kWh per year, resulting in %d kg of CO2" % (
		electricity_kwh_per_year, electricity.co2()
	)

	profile.delete()
 
## Authors 

Robin Houston and Tom Dyson, January 2010