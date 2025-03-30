from flask import Flask, render_template, request, jsonify
import pandas as pd
import time
import datetime
import urllib.parse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

# Chargement des données CTM
def load_ctm_data():
    df = pd.read_excel("bus_stops_data.xlsx")
    # Création d'un dictionnaire de villes CTM
    city_ids = {}
    city_list = []
    for index, row in df.iterrows():
        city_name = row['CityName']
        city_ids[city_name.lower()] = row['CityId']
        city_list.append({"name": city_name, "id": row['CityId'], "type": "CTM"})
    return city_ids, city_list

# Chargement des données ONCF
def load_oncf_data():
    df = pd.read_excel("oncf_data 1.xlsx")
    stations = df["Station"].dropna().unique().tolist()
    station_list = [{"name": station, "type": "ONCF"} for station in stations]
    return stations, station_list

# Charger les données
ctm_city_ids, ctm_cities = load_ctm_data()
oncf_stations, oncf_stations_list = load_oncf_data()

# Fusionner les listes de villes
all_locations = []
all_locations_dict = {}

# Ajouter les villes CTM
for city in ctm_cities:
    city_key = city["name"].lower()
    all_locations_dict[city_key] = {
        "name": city["name"],
        "ctm_id": city["id"],
        "services": ["CTM"]
    }

# Ajouter les stations ONCF
for station in oncf_stations_list:
    station_key = station["name"].lower()
    if station_key in all_locations_dict:
        # La ville existe déjà pour CTM, ajouter le service ONCF
        all_locations_dict[station_key]["services"].append("ONCF")
    else:
        # Nouvelle ville uniquement pour ONCF
        all_locations_dict[station_key] = {
            "name": station["name"],
            "services": ["ONCF"]
        }

# Convertir le dictionnaire en liste
for location in all_locations_dict.values():
    all_locations.append(location)

@app.route('/')
def index():
    return render_template('index_combined.html', locations=all_locations)

@app.route('/search', methods=['POST'])
def search():
    try:
        # Récupérer les données du formulaire
        data = request.get_json()
        departure_location = data.get('departureLocation')
        arrival_location = data.get('arrivalLocation')
        departure_date = data.get('departureDate')
        number_of_adults = int(data.get('numberOfAdults', 1))
        service_type = data.get('serviceType', 'all')  # 'all', 'ctm', 'oncf'
        
        results = {
            "success": True,
            "ctm_journeys": [],
            "oncf_journeys": []
        }
        
        # Vérifier les services disponibles pour ces villes
        dep_services = all_locations_dict.get(departure_location.lower(), {}).get("services", [])
        arr_services = all_locations_dict.get(arrival_location.lower(), {}).get("services", [])
        
        # Recherche CTM si disponible et demandé
        if "CTM" in dep_services and "CTM" in arr_services and (service_type == 'all' or service_type == 'ctm'):
            departure_city_id = all_locations_dict[departure_location.lower()]["ctm_id"]
            arrival_city_id = all_locations_dict[arrival_location.lower()]["ctm_id"]
            ctm_results = search_ctm(departure_city_id, arrival_city_id, departure_date, number_of_adults)
            results["ctm_journeys"] = ctm_results
        
        # Recherche ONCF si disponible et demandé
        if "ONCF" in dep_services and "ONCF" in arr_services and (service_type == 'all' or service_type == 'oncf'):
            oncf_results = search_oncf(departure_location, arrival_location, departure_date)
            results["oncf_journeys"] = oncf_results
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

def search_ctm(departure_city_id, arrival_city_id, departure_date, number_of_adults):
    # Configuration de Selenium pour CTM
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=options)
    # URL pour la page de réservation CTM
    url = f"https://booking.ctm.ma/journeys?oCity={departure_city_id}&dCity={arrival_city_id}&oDate={departure_date}&fareClasses=BONUS_SCHEME_GROUP.ADULT,{number_of_adults}"
    driver.get(url)
    
    # Attendre le chargement du contenu
    time.sleep(5)
    
    # Extraire le contenu HTML
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    # Extraire les détails des trajets
    buses = []
    for index, journey in enumerate(soup.find_all("div", class_="journey-row-wrapper")):
        try:
            departure_time = journey.find("div", class_="origin-info").find("span", class_="time").text.strip()
            departure_station = journey.find("div", class_="origin-info").find("span", class_="bus-stop-name").text.strip()
            arrival_time = journey.find_all("div", class_="bus-location-label")[1].find("span", class_="time").text.strip()
            arrival_station = journey.find_all("div", class_="bus-location-label")[1].find("span", class_="bus-stop-name").text.strip()
            duration = journey.find("div", class_="trip-duration").text.strip()
            price = journey.find("div", class_="journey-price").find("div", class_="price").text.strip()
            
            buses.append({
                "Departure Time": departure_time,
                "Departure Station": departure_station,
                "Arrival Time": arrival_time,
                "Arrival Station": arrival_station,
                "Duration": duration,
                "Price": price,
                "Service": "CTM"
            })
        except Exception as e:
            print(f"Erreur d'extraction CTM pour le trajet {index}: {e}")
    
    # Fermer le navigateur
    driver.quit()
    
    return buses

def search_oncf(departure_station, arrival_station, date_str):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    try:
        # Utilisation des options lors de la création du driver
        web = webdriver.Chrome()
        web.get("https://www.oncf-voyages.ma/")

        # Fermer les popups
        def close_popups():
            
            try:
                WebDriverWait(web, 2).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button.sc-popup-notification--cointainer-close'))
                ).click()
            except Exception:
                pass

            try:
                WebDriverWait(web, 2).until(
                    EC.element_to_be_clickable((By.XPATH, '//button[contains(., "Accepter")]'))
                ).click()
            except Exception:
                pass

        close_popups()

        # Sélection des gares avec vérification et plusieurs tentatives
        def select_station(element_id, station_name):
            for _ in range(3):  # 3 tentatives
                try:
                    element = WebDriverWait(web, 15).until(
                        EC.element_to_be_clickable((By.ID, element_id))
                    )
                    element.click()
                    element.send_keys(Keys.CONTROL + "a")
                    element.send_keys(Keys.DELETE)
                    element.send_keys(station_name)
                    time.sleep(1)  # Attente pour l'apparition des suggestions
                    element.send_keys(Keys.ARROW_DOWN)
                    element.send_keys(Keys.ENTER)
                    return
                except Exception as e:
                    print(f"Erreur sélection {station_name}: {str(e)}")
                    web.refresh()
                    close_popups()
                    time.sleep(2)
            raise Exception(f"Échec sélection de {station_name} après 3 tentatives")

        select_station('origin', departure_station)
        select_station('destination', arrival_station)

        # Vérification des erreurs dans le formulaire
        if web.find_elements(By.CSS_SELECTOR, '.error-message'):
            raise Exception("Erreur dans la sélection des gares")

        def select_date(day):
            date_input = WebDriverWait(web, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'input.CustomInput.CI_calendar'))
            )
            date_input.click()

            # Wait for the datepicker modal
            WebDriverWait(web, 10).until(
                EC.visibility_of_element_located((By.CLASS_NAME, 'react-datepicker'))
            )

            # Select March 21, 2025
            date_element = WebDriverWait(web, 10).until(
                EC.element_to_be_clickable((By.XPATH, f'//div[text()="{day}" and contains(@class, "react-datepicker__day") and not(contains(@class, "disabled"))]'))
            )
            date_element.click()

            # Optional: Select "Soir" time slot
            WebDriverWait(web, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//label[.//span[contains(text(), "Nuit")]]'))
            ).click()

            # Confirm selection
            WebDriverWait(web, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'button.DatePickerModal_confirm'))
            ).click()
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")  # Conversion en objet datetime
        day= date_obj.day  # Extraction du jour
        select_date(day)
        # Solution finale pour le bouton Rechercher
        def click_search_button():
            try:
                # Version 1: Sélecteur CSS
                search_btn = WebDriverWait(web, 30).until(
                    EC.element_to_be_clickable((
                        By.CSS_SELECTOR, 
                        'div.searchForm_footer > button.btn-primary'
                    ))
                )
                
                # Version 2: XPath alternatif
                if not search_btn.is_displayed():
                    search_btn = WebDriverWait(web, 10).until(
                        EC.element_to_be_clickable((
                            By.XPATH,
                            '//button[.//span[text()="Rechercher"]]'
                        ))
                    )
                
                # Vérifications finales
                print("État du bouton:")
                print("- Visible:", search_btn.is_displayed())
                print("- Activé:", search_btn.is_enabled())
                print("- Texte:", search_btn.text)
                
                # Forçage du clic si nécessaire
                web.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", search_btn)
                time.sleep(1)
                web.execute_script("arguments[0].click();", search_btn)
                print("Clic sur Rechercher effectué")
                
            except Exception as e:
                print("Échec du clic sur Rechercher:", str(e))
                web.save_screenshot('error_search.png')
                raise

        click_search_button()
        

        from bs4 import BeautifulSoup

        # Wait for the journey cards to appear
        try:
            WebDriverWait(web, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div.trips-wrapper'))
            )
            
            # Retrieve all journey cards which include both journey info and price info
            cards = web.find_elements(By.CSS_SELECTOR, 'div.trips-wrapper')
            results = []

            for card in cards:
                try:
                    # Scroll the card into view
                    web.execute_script("arguments[0].scrollIntoView(true);", card)
                    card_html = card.get_attribute('innerHTML')
                    soup = BeautifulSoup(card_html, 'html.parser')
                    
                    # --- Extract journey information ---
                    # Locate the journey details container (if present)
                    journey_section = soup.select_one('div.trajet-info')
                    if journey_section:
                        od_wrappers = journey_section.select('div.od-wrapper')
                        if len(od_wrappers) >= 2:
                            # Departure info: first od-wrapper
                            dep_date_elem = od_wrappers[0].select_one('label.date')
                            dep_station_elem = od_wrappers[0].select_one('label.station')
                            heure_depart = dep_date_elem.get_text(strip=True) if dep_date_elem else None
                            gare_depart = dep_station_elem.get_text(strip=True) if dep_station_elem else None

                            # Arrival info: second od-wrapper
                            arr_date_elem = od_wrappers[1].select_one('label.date')
                            arr_station_elem = od_wrappers[1].select_one('label.station')
                            heure_arrivee = arr_date_elem.get_text(strip=True) if arr_date_elem else None
                            gare_arrivee = arr_station_elem.get_text(strip=True) if arr_station_elem else None
                        else:
                            heure_depart = gare_depart = heure_arrivee = gare_arrivee = None
                    else:
                        heure_depart = gare_depart = heure_arrivee = gare_arrivee = None

                    # Journey duration (if available)
                    duree_elem = soup.select_one('.trip-duration')
                    duree_trajet = duree_elem.get_text(strip=True) if duree_elem else None

                    # --- Extract footer details: "classe" & "type de train" ---
                    # They appear inside a span with the class TripCardFooter_Correspondance_description_span.
                    footer_elem = soup.select_one('span.TripCardFooter_Correspondance_description_span')
                    if footer_elem:
                        # Use stripped_strings to capture all text (including within SVG if available)
                        footer_text = " ".join(list(footer_elem.stripped_strings))
                        # Often the text may look like: "TL 2nd Class" (or similar)
                        # Remove the prefix "TL" if present:
                        classe = footer_text.replace("TL", "").strip()
                        # For type_train, you might want to use the first word or customize as needed.
                        # Here we simply split the footer text and take the first word.
                        type_train = footer_text.split()[0] if footer_text.split() else None
                    else:
                        classe = type_train = None

                    # --- Extract Price ---
                    # Assuming the price is within a sibling container with class "choose-destination"
                    price_elem = soup.select_one('div.choose-destination label.price')
                    price = price_elem.get_text(strip=True) if price_elem else None

                    infos = {
                        'heure_depart': heure_depart,
                        'gare_depart': gare_depart,
                        'duree_trajet': duree_trajet,
                        'heure_arrivee': heure_arrivee,
                        'gare_arrivee': gare_arrivee,
                        'classe': classe,
                        'type_train': type_train,
                        'price': price
                    }
                    formatted_infos = {
    "Departure Time": infos['heure_depart'],
    "Departure Station": infos['gare_depart'],
    "Arrival Time": infos['heure_arrivee'],
    "Arrival Station": infos['gare_arrivee'],
    "Duration": infos['duree_trajet'],
    "Price": infos['price'],
    "Service": "ONCF"  # Si c'est pour l'ONCF, sinon remplace par "CTM" si nécessaire
}
                    results.append(formatted_infos)
                except Exception as e:
                    print(f"Erreur sur une carte: {str(e)}")
                    continue

            return results

        except Exception as e:
            print(f"ERREUR SCRAPING ONCF: {str(e)}")
            if 'web' in locals():
                web.save_screenshot('oncf_error.png')
            return []

    finally:
     if 'web' in locals():
         web.quit()


@app.route('/get_locations', methods=['GET'])
def get_locations():
    query = request.args.get('query', '').lower()
    if not query:
        return jsonify([])
    
    filtered_locations = [location for location in all_locations if query in location['name'].lower()]
    return jsonify(filtered_locations[:10])  # Limiter à 10 résultats

if __name__ == '__main__':
    # Lancer l'application Flask pour qu'elle soit accessible sur tout le réseau
    app.run(debug=True, host='0.0.0.0', port=5000)