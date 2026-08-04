# Shared lookup used by both routes/campaigns.rb and routes/dm.rb (DM tools
# always operate against an existing campaign).

def campaign_exists?(campaign_id)
  !db.execute('SELECT 1 FROM campaigns WHERE id = ?', [campaign_id]).first.nil?
end
