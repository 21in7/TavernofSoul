from django.shortcuts import render
from os.path import join
from Items.models import Items
from Monsters.models import Monsters 
from Jobs.models import Jobs
from Skills.models import Skills
from Attributes.models import Attributes 
from Maps.models import Maps
from Dashboard.models import Version
from django.http import HttpResponse

# Create your views here.
APP_NAME = "Dashboard"

def Ads(request):
	return HttpResponse("google.com, pub-2728591277096799, DIRECT, f08c47fec0942fa0")

def index(request):

	FUNCT_NAME = 'index'
	if 'q' in request.GET:
		query = request.GET['q']
		data = {}
		data['item'] = Items.objects.filter(name__icontains = query).select_related('equipments')
		data['item_len'] = data['item'].count()
		data['item'] = data['item'] [:5]

		data['monster'] = Monsters.objects.filter(name__icontains = query)
		data['monster_len'] = data['monster'].count()
		data['monster'] = data['monster'] [:5]
		data['query'] = query

		data['maps'] = Maps.objects.filter(name__icontains=query)
		data['maps_len'] = data['maps'].count()
		data['maps'] = data['maps'][:5]

		data['jobs'] = Jobs.objects.filter(name__icontains=query)
		data['jobs_len'] = data['jobs'].count()
		data['jobs'] = data['jobs'][:5]

		att = Attributes.objects.filter(name__icontains=query)

		
		data['attributes_len'] = att.count()
		data['attributes'] = []
		for i in att[:5]:
			i.descriptions = i.descriptions.split("{nl}")
			data['attributes'].append(i)

		data['skills'] = Skills.objects.filter(name__icontains=query).select_related('job')
		data['skills_len'] = data['skills'].count()
		data['skills'] = data['skills'][:5]

		return render(request, join(APP_NAME,"search.html"), data)	
	else:
		ver = Version.objects.latest('created')
		context = {"version" : ver.version}
		return render(request, join(APP_NAME,"index.html"), context)
