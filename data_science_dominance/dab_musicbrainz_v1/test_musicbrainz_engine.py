from __future__ import annotations

import inspect
import unittest

import musicbrainz_engine as engine


def track(
    track_id: int,
    title: str,
    artist: str,
    album: str = "",
    year: str = "2020",
    length: str = "240",
    language: str = "English",
    source_id: int = 1,
    source_track_id: str | None = None,
) -> engine.Track:
    return engine.Track(
        track_id=track_id,
        source_id=source_id,
        source_track_id=source_track_id or f"s{track_id}",
        title=title,
        artist=artist,
        album=album,
        year=engine.parse_year(year),
        length_seconds=engine.parse_length_seconds(length),
        language=language,
    )


def sale(
    sale_id: int,
    track_id: int,
    country: str,
    store: str,
    units: float,
    revenue: float,
) -> engine.Sale:
    return engine.Sale(
        sale_id=sale_id,
        track_id=track_id,
        country=country,
        store=store,
        units_sold=units,
        revenue_usd=revenue,
    )


class NormalizationTests(unittest.TestCase):
    def test_unicode_and_editions(self):
        self.assertEqual(engine.artist_key("Beyoncé"), engine.artist_key("Beyonce"))
        self.assertEqual(
            engine.title_key("Get Me Bodied (Remastered 2020)"),
            engine.title_key("Get Me Bodied"),
        )

    def test_year_and_length(self):
        self.assertEqual(engine.parse_year("released 1999-04-01"), 1999)
        self.assertEqual(engine.parse_length_seconds("3:30"), 210.0)
        self.assertEqual(engine.parse_length_seconds("1:02:03"), 3723.0)


class EntityResolutionTests(unittest.TestCase):
    def test_exact_semantic_duplicates_merge(self):
        tracks = [
            track(1, "Get Me Bodied", "Beyoncé", "B'Day", "2006", "3:25", source_id=1),
            track(2, "Get Me Bodied (Remastered 2020)", "Beyonce", "B Day", "2006", "205", source_id=2),
            track(3, "Halo", "Beyoncé", "I Am... Sasha Fierce", "2008", "4:21"),
        ]
        entities, mapping = engine.resolve_entities(tracks)
        self.assertEqual(len(entities), 2)
        self.assertEqual(mapping[1], mapping[2])
        self.assertNotEqual(mapping[1], mapping[3])

    def test_similar_but_distinct_songs_do_not_merge(self):
        tracks = [
            track(1, "Love Song", "Artist A", "Album", "2020", "200"),
            track(2, "Love Songs", "Artist A", "Album", "2020", "240"),
        ]
        entities, _ = engine.resolve_entities(tracks)
        self.assertEqual(len(entities), 2)

    def test_same_source_identifier_with_compatible_metadata(self):
        tracks = [
            track(1, "One More Time", "Daft Punk", "Discovery", source_track_id="abc", source_id=1),
            track(2, "One More Time [Original Version]", "Daft Punk", "Discovery", source_track_id="ABC", source_id=2),
        ]
        entities, mapping = engine.resolve_entities(tracks)
        self.assertEqual(len(entities), 1)
        self.assertEqual(mapping[1], mapping[2])


class PlannerTests(unittest.TestCase):
    def test_public_query1_plan(self):
        query = "How much revenue in USD did Apple Music make from Beyoncé's song 'Get Me Bodied' in Canada?"
        plan = engine.plan_query(query)
        self.assertEqual(plan.measure, "revenue_usd")
        self.assertEqual(plan.aggregate, "sum")
        self.assertFalse(plan.group_by)
        predicate_map = {(p.field, engine.key(p.value)) for p in plan.predicates}
        self.assertIn(("country", "canada"), predicate_map)
        self.assertIn(("store", "applemusic"), predicate_map)
        self.assertIn(("artist", "beyonce"), predicate_map)
        self.assertIn(("title", "getmebodied"), predicate_map)

    def test_top_artist_revenue(self):
        plan = engine.plan_query("Which artist generated the highest total revenue in Germany?")
        self.assertEqual(plan.group_by, ["artist"])
        self.assertEqual(plan.direction, "max")
        self.assertEqual(plan.measure, "revenue_usd")
        self.assertEqual(plan.aggregate, "sum")

    def test_top_three_tracks_by_units(self):
        plan = engine.plan_query("What are the top 3 tracks by units sold on Spotify?")
        self.assertEqual(plan.group_by, ["title"])
        self.assertEqual(plan.top_k, 3)
        self.assertEqual(plan.measure, "units_sold")
        self.assertEqual(plan.direction, "max")

    def test_minimum_support_and_mean(self):
        plan = engine.plan_query(
            "Which album has the highest average revenue among albums with at least 2 distinct tracks?"
        )
        self.assertEqual(plan.group_by, ["album"])
        self.assertEqual(plan.aggregate, "mean")
        self.assertEqual(plan.min_support, 2)
        self.assertEqual(plan.support_field, "entity_id")

    def test_decade_and_language(self):
        plan = engine.plan_query(
            "Which artist sold the most units for Spanish-language songs released in the 1990s?"
        )
        self.assertEqual(plan.group_by, ["artist"])
        self.assertEqual(plan.measure, "units_sold")
        predicates = {(p.field, p.operator, engine.key(p.value)) for p in plan.predicates}
        self.assertIn(("language", "eq", "spanish"), predicates)
        self.assertIn(("decade", "eq", "1990"), predicates)

    def test_revenue_share(self):
        plan = engine.plan_query("Which country had the largest share of total revenue?")
        self.assertEqual(plan.group_by, ["country"])
        self.assertTrue(plan.share)
        self.assertEqual(plan.aggregate, "share")

    def test_revenue_per_unit(self):
        plan = engine.plan_query("Which store had the highest revenue per unit?")
        self.assertEqual(plan.group_by, ["store"])
        self.assertEqual(plan.measure, "revenue_per_unit")
        self.assertEqual(plan.aggregate, "ratio")

    def test_no_holdout_leakage(self):
        source = inspect.getsource(engine).lower()
        self.assertNotIn("query2", source)
        self.assertNotIn("query3", source)
        self.assertNotIn("ground_truth", source)
        self.assertNotIn("validate.py", source)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tracks = [
            track(1, "Get Me Bodied", "Beyoncé", "B'Day", "2006", "3:25", source_id=1),
            track(2, "Get Me Bodied (Remastered 2020)", "Beyonce", "B Day", "2006", "205", source_id=2),
            track(3, "Halo", "Beyoncé", "I Am... Sasha Fierce", "2008", "4:21"),
            track(4, "One More Time", "Daft Punk", "Discovery", "2001", "5:20"),
            track(5, "Harder Better Faster Stronger", "Daft Punk", "Discovery", "2001", "3:45"),
            track(6, "La Vida", "Artista Uno", "Álbum Español", "1998", "3:00", "Spanish"),
        ]
        self.sales = [
            sale(1, 1, "Canada", "Apple Music", 10, 500.00),
            sale(2, 2, "Canada", "Apple Music", 12, 559.46),
            sale(3, 1, "USA", "Spotify", 20, 200.00),
            sale(4, 3, "Canada", "Apple Music", 5, 250.00),
            sale(5, 4, "Germany", "Spotify", 30, 600.00),
            sale(6, 5, "Germany", "Spotify", 15, 450.00),
            sale(7, 6, "France", "iTunes", 50, 1000.00),
        ]
        self.entities, self.facts = engine.build_facts(self.tracks, self.sales)
        self.known = {
            "artist": [entity.artist for entity in self.entities],
            "album": [entity.album for entity in self.entities],
            "title": [entity.title for entity in self.entities],
        }

    def evaluate(self, query):
        plan = engine.plan_query(query, self.known)
        return plan, engine.evaluate(plan, self.facts)

    def test_public_query1_answer(self):
        plan, answer = self.evaluate(
            "How much revenue in USD did Apple Music make from Beyoncé's song 'Get Me Bodied' in Canada?"
        )
        self.assertAlmostEqual(answer, 1059.46, places=2)

    def test_duplicate_sales_aggregate_under_one_track(self):
        plan, answer = self.evaluate("Which track generated the most revenue in Canada?")
        self.assertEqual(answer[0][0][0], "Get Me Bodied")
        self.assertAlmostEqual(answer[0][1], 1059.46, places=2)

    def test_artist_revenue(self):
        plan, answer = self.evaluate("Which artist generated the highest total revenue in Germany?")
        self.assertEqual(engine.artist_key(answer[0][0][0]), "daftpunk")
        self.assertEqual(answer[0][1], 1050.0)

    def test_album_minimum_support(self):
        plan, answer = self.evaluate(
            "Which album has the highest average revenue among albums with at least 2 distinct tracks?"
        )
        self.assertEqual(engine.album_key(answer[0][0][0]), "discovery")

    def test_distinct_tracks(self):
        plan, answer = self.evaluate("How many distinct tracks does Beyoncé have?")
        self.assertEqual(answer, 2.0)

    def test_language_and_decade(self):
        plan, answer = self.evaluate(
            "Which artist sold the most units for Spanish-language songs released in the 1990s?"
        )
        self.assertEqual(engine.artist_key(answer[0][0][0]), "artistauno")

    def test_country_share(self):
        plan, answer = self.evaluate("Which country had the largest share of total revenue?")
        self.assertEqual(answer[0][0][0], "Canada")
        total = sum(sale.revenue_usd for sale in self.sales)
        self.assertAlmostEqual(answer[0][1], 1309.46 / total)

    def test_store_revenue_per_unit(self):
        plan, answer = self.evaluate("Which store had the highest revenue per unit?")
        self.assertEqual(answer[0][0][0], "Apple Music")

    def test_top_two_tracks(self):
        plan, answer = self.evaluate("What are the top 2 tracks by units sold?")
        self.assertEqual(len(answer), 2)
        self.assertEqual(answer[0][0][0], "La Vida")

    def test_composite_grouping(self):
        plan = engine.Plan(
            group_by=["artist", "album"],
            measure="revenue_usd",
            aggregate="sum",
            direction="max",
            top_k=1,
        )
        answer = engine.evaluate(plan, self.facts)
        self.assertEqual(engine.artist_key(answer[0][0][0]), "beyonce")
        self.assertEqual(engine.album_key(answer[0][0][1]), "bday")

    def test_render_scalar_and_ranking(self):
        plan = engine.Plan()
        self.assertEqual(engine.render_answer(1059.46, plan), "1059.46")
        ranking = [(("Beyoncé",), 1309.46)]
        self.assertTrue(engine.render_answer(ranking, plan).startswith("Beyoncé:"))


class RelationalAlgebraTests(unittest.TestCase):
    def setUp(self):
        tracks = [
            track(1, "Song A", "Artist A", "Album A", "2010", "200"),
            track(2, "Song B", "Artist A", "Album A", "2011", "210"),
            track(3, "Song C", "Artist B", "Album B", "2012", "220"),
            track(4, "Song D", "Artist C", "Album C", "2013", "230"),
        ]
        sales = [
            sale(1, 1, "Canada", "Spotify", 10, 100),
            sale(2, 1, "USA", "Spotify", 5, 40),
            sale(3, 2, "Canada", "Apple Music", 20, 300),
            sale(4, 2, "USA", "Apple Music", 20, 200),
            sale(5, 3, "Canada", "Spotify", 4, 40),
            sale(6, 3, "USA", "Spotify", 10, 150),
            sale(7, 4, "Canada", "Amazon Music", 1, 20),
            sale(8, 4, "USA", "Amazon Music", 1, 20),
            sale(9, 4, "UK", "Amazon Music", 1, 20),
            sale(10, 4, "Germany", "Amazon Music", 1, 20),
            sale(11, 4, "France", "Amazon Music", 1, 20),
        ]
        self.entities, self.facts = engine.build_facts(tracks, sales)

    def test_having_and_count_groups(self):
        plan = engine.plan_query("How many artists generated more than $200 in revenue?")
        self.assertTrue(plan.count_groups)
        self.assertEqual(plan.having_operator, "gt")
        self.assertEqual(engine.evaluate(plan, self.facts), 1)

    def test_all_country_coverage(self):
        plan = engine.plan_query("Which tracks were sold in all five countries?")
        result = engine.evaluate(plan, self.facts)
        self.assertEqual([engine.title_key(item[0][0]) for item in result], ["songd"])

    def test_country_contrast(self):
        plan = engine.plan_query("Which artists generated more revenue in Canada than USA?")
        self.assertEqual(plan.contrast_field, "country")
        self.assertEqual(plan.contrast_left, "Canada")
        self.assertEqual(plan.contrast_right, "USA")
        result = engine.evaluate(plan, self.facts)
        self.assertEqual(
            {engine.artist_key(item[0][0]) for item in result},
            {"artista"},
        )

    def test_country_ratio_argmax(self):
        plan = engine.plan_query(
            "Which artist had the highest ratio of revenue in Canada to USA?"
        )
        result = engine.evaluate(plan, self.facts)
        self.assertEqual(engine.artist_key(result[0][0][0]), "artista")

    def test_scalar_share_with_context(self):
        plan = engine.plan_query(
            "What percentage of Canadian revenue came from Spotify?"
        )
        value = engine.evaluate(plan, self.facts)
        self.assertAlmostEqual(value, 140 / 460)

    def test_normalized_revenue_per_distinct_track(self):
        plan = engine.plan_query(
            "Which artist had the highest revenue per distinct track?"
        )
        result = engine.evaluate(plan, self.facts)
        self.assertEqual(engine.artist_key(result[0][0][0]), "artista")

    def test_top_five_word_form(self):
        plan = engine.plan_query("What are the top five artists by revenue?")
        self.assertEqual(plan.group_by, ["artist"])
        self.assertEqual(plan.top_k, 5)

    def test_list_all_groups_without_ranking(self):
        plan = engine.plan_query("For each country, compute total revenue.")
        self.assertEqual(plan.group_by, ["country"])
        self.assertIsNone(plan.direction)
        result = engine.evaluate(plan, self.facts)
        self.assertEqual(len(result), 5)

    def test_group_count_without_having(self):
        plan = engine.plan_query("How many countries generated revenue?")
        self.assertTrue(plan.count_groups)
        self.assertEqual(engine.evaluate(plan, self.facts), 5)


class EntityResolutionStressTests(unittest.TestCase):
    def test_many_duplicate_variants_and_no_false_merges(self):
        tracks = []
        expected_groups = 120
        track_id = 1
        for group in range(expected_groups):
            base_title = f"Signal Song {group:03d}"
            artist = f"Artist {group % 17:02d}"
            album = f"Album {group % 23:02d}"
            for variant in range(3):
                title_value = (
                    base_title
                    if variant == 0
                    else f"{base_title} (Remastered {2018 + variant})"
                )
                artist_value = artist if variant != 2 else artist.replace(" ", "  ")
                album_value = album if variant != 1 else album.replace(" ", "-")
                tracks.append(
                    track(
                        track_id,
                        title_value,
                        artist_value,
                        album_value,
                        str(2000 + group % 20),
                        str(180 + group % 60),
                        source_id=variant + 1,
                    )
                )
                track_id += 1
        entities, mapping = engine.resolve_entities(tracks)
        self.assertEqual(len(entities), expected_groups)
        for group in range(expected_groups):
            ids = [group * 3 + 1, group * 3 + 2, group * 3 + 3]
            self.assertEqual(len({mapping[item] for item in ids}), 1)


if __name__ == "__main__":
    unittest.main()
