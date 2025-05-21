def generate_summary_article(jobs):
    """Generate a markdown summary article from job data"""
    if not jobs:
        return "No positions found."
        
    article = "# DAAD PhD Position Opportunities\n\n"
    article += f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
    
    for i, job in enumerate(jobs, 1):
        title = job.get('title', '').strip()
        if not title:
            continue
        
        article += f"## {i}. {title}\n\n"
        
        if job.get('highlight'):
            highlight = job['highlight'].strip()
            if highlight:
                article += f"**Highlights:** {highlight}\n\n"
            
        if job.get('institution'):
            inst = job['institution'].strip()
            if inst:
                article += f"**Institution:** {inst}\n\n"
            
        if job.get('requirements'):
            reqs = format_requirements(job['requirements'])
            if reqs:
                article += f"**Requirements:** {reqs}\n\n"
                
        if job.get('location'):
            loc = job['location'].strip()
            if loc:
                article += f"**Location:** {loc}\n\n"
            
        article += f"**More Info:** [Position Details]({job.get('link', '#')})\n\n"
        article += "---\n\n"
    
    return article
