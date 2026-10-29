       SIGNED_TO
(:Artist) ────────► (:Label)


                COLLABORATED_WITH
(:Artist) ◄──────────────────────► (:Artist)


        PERFORMED_BY / FEATURES
(:Song) ────────────────────────► (:Artist)



Relationship	               Direction	                                  Meaning
COLLABORATED_WITH	   Artist ↔ Artist (undirected in practice)	    two artists have worked together directly
PERFORMED_BY | FEATURES	       Song → Artist	                    a song's main performer or featured artist
SIGNED_TO	             Artist → Label	                             which label an artist belongs to