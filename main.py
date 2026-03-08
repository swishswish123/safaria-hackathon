import requests
import time

def get_this_weeks_parasha():
    url = "https://www.sefaria.org/api/calendars"

    # Make a GET request to the URL
    response = requests.get(url)

    # Parse the response as JSON
    data = response.json()  


    # Retrieve the list of calendar_items
    calendar_items = data['calendar_items']

    # get this week's parasha
    for item in calendar_items:
        if item['title']['en'] == 'Parashat Hashavua':
            parasha_ref = item['ref'] 
            parasha_name = item['displayValue']['en']

        if item["title"]["en"] == "Haftarah":
            haftarah_ref = item['ref']
            haftarah_name = item['displayValue']['en']

    return parasha_ref, parasha_name, haftarah_ref, haftarah_name


def get_parasha_text(parasha_ref):
    url = f"https://www.sefaria.org/api/texts/{parasha_ref}"
    response = requests.get(url)
    data = response.json()
    parasha_text = data['he']  # Get the Hebrew text of the parasha
    return parasha_text


def get_haftarah_text(haftarah_ref):
    url = f"https://www.sefaria.org/api/texts/{haftarah_ref}"
    response = requests.get(url)
    data = response.json()
    haftarah_text = data['he']  # Get the Hebrew text of the haftarah
    return haftarah_text

def get_recordings(haftarah_ref):
    url = f"https://www.sefaria.org/api/related/{haftarah_ref}"
    response = requests.get(url)
    data = response.json()
    recordings = data['media']  # Get the list of recordings related to the haftarah
    for recording in recordings:
        anchorRef = recording['anchorRef']  # Get the reference of the recording
        media_url = recording['media_url']  # Get the URL of the recording
        print(f"Recording for {anchorRef}: {media_url}")

        # play the recording here-----
        
        # get corresponding text for the recording
        recording_text = get_parasha_text(anchorRef)
        print(f"Text for {anchorRef}: {recording_text}")
    

def main(): 

    # get this weeks parasha
    parasha_ref, parasha_name, haftarah_ref, haftarah_name = get_this_weeks_parasha()
    print(f"This week's parasha is {parasha_name} ({parasha_ref})")
    print(f"This week's haftarah is {haftarah_name} ({haftarah_ref})")

    # get the text of this weeks parasha
    parasha_text = get_parasha_text(parasha_ref)
    print(f"The text of this week's parasha is:\n{parasha_text}")

    # get the haftarah audio recording
    get_recordings(parasha_ref)

    # get the text of this weeks haftarah
    haftarah_text = get_haftarah_text(haftarah_ref)
    print(f"The text of this week's haftarah is:\n{haftarah_text}")

    return parasha_ref, parasha_name

if __name__=='__main__': 
    main() 