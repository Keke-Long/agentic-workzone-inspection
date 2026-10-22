import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
plt.rcParams['font.family']='DejaVu Sans'
fig,ax=plt.subplots(figsize=(12,10)); ax.set_xlim(0,12); ax.set_ylim(0,10); ax.axis('off'); fig.subplots_adjust(0,0,1,1)
ink='#183047'; blue='#28618B'; teal='#14786F'
def box(x,y,w,h,fc='#F4F7FA',ec='#B8C8D6',lw=1.3):
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.025,rounding_size=0.10',fc=fc,ec=ec,lw=lw))
def text(x,y,s,size=16,weight='normal',color=ink,ha='left'):
 ax.text(x,y,s,fontsize=size,fontweight=weight,color=color,ha=ha,va='top',linespacing=1.4)
def arrow(x1,y1,x2,y2): ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2),arrowstyle='-|>',mutation_scale=17,lw=1.6,color=blue))
box(.18,9.02,7.1,.78); text(.4,9.62,'CONNECTED-VEHICLE INPUT',14,'bold',blue);text(.4,9.32,'Camera imagery + LiDAR point clouds',18)
box(7.55,9.02,4.25,.78);text(7.78,9.62,'REGULATORY KNOWLEDGE',14,'bold',teal);text(7.78,9.32,'MUTCD structure + source text',16)
arrow(3.7,9.0,3.7,8.71); arrow(9.65,9.0,9.65,8.71)
box(.18,7.75,11.62,.94);text(.4,8.48,'STAGE 1   Layout selection',20,'bold');text(.4,8.06,'Scene context → source-supported Typical Application',15)
arrow(3.7,7.73,3.7,7.4)
box(.18,5.22,11.62,2.15,fc='#EDF7F5',ec=teal,lw=2);text(.4,7.17,'STAGE 2   Regulation-grounded inspection planning',20,'bold',teal)
for x,title,body in [(0.42,'Structured retrieval','TA-core + condition KG\nBM25 gap retrieval'),(4.27,'Requirement construction','Applicability + atomic checks\nSource, modality, inputs'),(8.12,'Evidence planning','Data availability\nAcquisition / tool plan')]:
 box(x,5.76,3.42,.89,fc='white',ec='#B5D9D1');text(x+.12,6.51,title,14,'bold');text(x+.12,6.22,body,13)
arrow(3.9,6.18,4.23,6.18);arrow(7.75,6.18,8.08,6.18)
text(.43,5.55,'OUTPUT   Source-linked requirements + evidence acquisition plan',16,'bold',teal)
arrow(6,5.20,6,4.9)
box(.18,3.35,11.62,1.53);text(.4,4.67,'STAGE 3   Tool-assisted inspection and assessment',20,'bold')
text(.42,4.22,'Select / call tools → observations + measurements → assess each requirement',15)
text(.42,3.81,'Inspect intermediate evidence; acquire further evidence when needed and available',14)
arrow(6,3.33,6,3.04)
box(.18,2.00,11.62,1.01);text(.4,2.82,'STAGE 4   Inspection report synthesis',20,'bold');text(.42,2.37,'Consolidate conclusions, citations and evidence; group shared physical issues',15)
arrow(6,1.98,6,1.7)
box(.18,.13,11.62,1.55,fc='#FFF9EF',ec='#C79A48',lw=1.5)
text(.42,1.48,'TRACEABLE INSPECTION REPORT',17,'bold','#846020')
text(.42,1.10,'Scene / layout summary   •   Requirement-level results   •   Issue evidence',15)
text(.42,.77,'Each record: requirement + MUTCD citation + image / measurement + rationale',14)
for x,label,c in [(.43,'SATISFIED','#20745B'),(3.28,'DEFICIENT','#AD493A'),(6.25,'NOT ASSESSED','#856520')]: text(x,.43,label,14,'bold',c)
text(8.65,.43,'+ coverage-gap reasons',13)
fig.savefig('.docs-methodology/assets/framework.png',dpi=250,facecolor='white')
fig.savefig('.docs-methodology/assets/framework.svg',facecolor='white')
