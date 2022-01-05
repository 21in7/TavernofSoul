import math

def makePagination(request, data, pages, page_length):
    if data['curpage']<int(page_length/2):
        page_true = pages[:page_length]
    elif data['curpage'] > len(pages)- int(page_length/2):
        key = len(pages) - page_length
        if key <0:
            key = 0
        page_true = pages[key :]
    else:
        page_true = pages[math.ceil(data['curpage'] - (page_length/2)):math.floor(data['curpage'] + (page_length/2))] #there's 0 
    pages = page_true

    data['pages'] = []
    path = request.get_full_path()
    if 'page' in path:
        path = path.split('&')
        path = "&".join(path[:-1])

    for i in pages:
        if('?' in path):
            link =  path + "&page="+str(i)
        else:
            link =  path + "?page="+str(i)
        data['pages'].append({'page':i, 'link':link})

    if ("?" in path):
        data['pageStart'] = path+'&page=1'

        data['pageNextLink'] = path+'&page='+str(data['curpage']+1)
        data['pageEnd'] = path+'&page='+str(math.ceil(data['item_len']/20))
    else:
        data['pageStart'] = path+'?page=1'
        data['pageNextLink'] = path+'?page='+str(data['curpage']+1)
        data['pageEnd'] = path+'?page='+str(math.ceil(data['item_len']/20))


    
    
    
    data['pageLen'] = math.ceil(data['item_len']/20)
    data['beforeEnd'] = data['pageLen']-2

def escaper(string):
    string = str(string)
    escaped = string.translate(str.maketrans({"-":  r"\-",
                                          "]":  r"\]",
                                          "\\": r"\\",
                                          "^":  r"\^",
                                          "$":  r"\$",
                                          "*":  r"\*",
                                          ".":  r"\.",
                                          "'" : r"\'",
                                          '"' : r'\"',
                                          ',' :r''
                                          
                                          }))
    return escaped
def getFromGet(request, index, default = ''):
    try:
        out     = request.GET[index] 
    except:
        out     = default
    if out == '':
        return default
    return out
def linebreaker(string):
    return string.split("{nl}")
